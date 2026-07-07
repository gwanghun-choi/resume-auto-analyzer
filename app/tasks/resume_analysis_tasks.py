from celery.exceptions import Retry

from app.core.celery_app import celery_app
from app.services import resume_analysis_db_service
from app.services.resume_analysis_service import ResumeAnalysisService, ResumeAnalysisError
from app.services.google_drive_service import build_authenticated_drive, DriveConfigError, _log

# 이력서 분석 Celery task (2차: resume_analysis 큐).
#
# API(/api/resumes/analyze-posting·analyze-selected·analyze-all)는 즉시 이 task 를 enqueue 하고
# QUEUED 로 응답합니다. worker 가 posting_id 기준으로 기존 로직을 그대로 재사용합니다:
#   resume_analysis_service.analyze_posting(posting_id, resume_file_ids)
#     → Drive download → PDF/DOCX parse → OpenAI 분석 → matching score → completed/failed 이동 → DB 저장
#
# 원칙:
#  - task payload 는 primitive(posting_id, resume_file_ids, requested_by_user_id) 만.
#    API 요청 db 세션/ORM 객체를 넘기지 않습니다.
#  - DB 세션은 재사용하는 service/ db_service 가 각 호출마다 SessionLocal 로 새로 열고 닫습니다.
#  - 파일 단위 성공/실패 격리는 기존 analyze_posting 로직을 그대로 유지합니다.
#  - 이미 COMPLETED/FAILED 인 파일은 PENDING 이 아니므로 재분석되지 않습니다(멱등/재실행 안전).
#  - 로그는 posting_id / 파일 수 / 상태 정도만. (이력서 원문 / LLM prompt·response / HTML 전문 로그 금지)
#
# 권한: API 진입 시점에 검사(ADMIN/MANAGER, 공고 권한 범위). worker 는 세션이 없으므로
#       requested_by_user_id 는 기록/로그용으로만 사용합니다.


@celery_app.task(bind=True, name="app.tasks.resume_analysis_tasks.analyze_resume_posting_task",
                 max_retries=2, default_retry_delay=60)
def analyze_resume_posting_task(self, posting_id: int, resume_file_ids: list = None,
                                requested_by_user_id: int = None):
    """공고 기준 이력서 분석. resume_file_ids 가 주어지면 그 파일들로만(선택 항목 분석).
    task 상태: COMPLETED / PARTIAL_FAILED / FAILED (파일 단위 실패는 기존 로직대로 격리)."""
    n = len(resume_file_ids) if resume_file_ids else "all"
    _log(f"[resume-analysis-task] start posting_id={posting_id} files={n} by={requested_by_user_id}")

    # worker-side 재검증: 공고/활성 JD/대기 파일 (권한은 API 에서 이미 검사)
    ctx = resume_analysis_db_service.get_posting_analysis_context(posting_id)
    if ctx is None:
        _log(f"[resume-analysis-task] posting not found posting_id={posting_id}")
        return {"posting_id": posting_id, "status": "FAILED", "step": "posting_not_found"}
    if ctx["jd"] is None:
        _log(f"[resume-analysis-task] no active JD posting_id={posting_id}")
        return {"posting_id": posting_id, "status": "FAILED", "step": "active_jd_not_found"}
    pending = resume_analysis_db_service.get_pending_files_for_posting(posting_id, resume_file_ids)
    if not pending:
        _log(f"[resume-analysis-task] no pending posting_id={posting_id} (skip)")
        return {"posting_id": posting_id, "status": "COMPLETED", "step": "no_pending_resumes",
                "total": 0, "success": 0, "failed": 0}

    # Drive 인증 (분석 시작 전 — 실패 시 아직 처리된 파일이 없어 재시도 안전)
    try:
        drive = build_authenticated_drive()
    except DriveConfigError as e:
        _log(f"[resume-analysis-task] drive auth failed posting_id={posting_id} retry")
        raise self.retry(exc=e)

    # 분석 실행 — 기존 로직 그대로 재사용 (프롬프트/점수/Drive 이동 불변, 파일 단위 격리)
    try:
        result = ResumeAnalysisService(drive).analyze_posting(posting_id, resume_file_ids=resume_file_ids)
    except Retry:
        raise
    except ResumeAnalysisError as e:
        # 사전검증성 실패(JD/폴더 등). 이 시점엔 파일 처리 전이라 상태 변경 없음.
        _log(f"[resume-analysis-task] precheck failed posting_id={posting_id} step={e.step}")
        return {"posting_id": posting_id, "status": "FAILED", "step": e.step}
    except Exception as e:
        # 예상 밖 오류(중간 실패). 이미 처리된 파일은 COMPLETED/FAILED 로 커밋됨, 미처리 파일은 PENDING 유지
        # → 재실행 시 남은 PENDING 만 처리(멱등). broad retry 는 OpenAI 비용 고려해 하지 않음.
        _log(f"[resume-analysis-task] unexpected error posting_id={posting_id} type={type(e).__name__}")
        return {"posting_id": posting_id, "status": "FAILED", "step": "unexpected_error"}

    total = result.get("total_pending_files", 0)
    success = result.get("completed_count", 0)
    failed = result.get("failed_count", 0)
    if failed == 0:
        status = "COMPLETED"
    elif success == 0:
        status = "FAILED"
    else:
        status = "PARTIAL_FAILED"
    _log(f"[resume-analysis-task] done posting_id={posting_id} total={total} "
         f"success={success} failed={failed} status={status}")
    return {"posting_id": posting_id, "status": status,
            "total": total, "success": success, "failed": failed}
