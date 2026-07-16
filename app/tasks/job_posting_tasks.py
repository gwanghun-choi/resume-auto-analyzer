from celery.exceptions import Retry
from fastapi import HTTPException

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.db.models.job_posting import JobPosting
from app.db.models.user import User
from app.schemas.job_posting_schema import JDUpsertRequest
from app.services import job_posting_service, job_extract_service
from app.services.job_extract_service import JobExtractError
from app.services.google_drive_service import build_authenticated_drive, DriveConfigError, _log

# 공고 JD 분석 Celery task (1차: job_discovery 큐).
#
# 사람인 배치가 신규 공고를 job_postings 에 insert 하고 posting_id 만 큐에 넣습니다.
# 이 task 는 posting_id 로 공고를 다시 조회해 기존 로직을 재사용합니다:
#   job_extract_service.extract_from_url(상세 URL 분석/LLM) → job_posting_service.upsert_jd(JD 저장 + Drive 폴더)
#
# 원칙:
#  - task payload 는 primitive(posting_id, requested_by_user_id) 만. API 요청 db 세션을 넘기지 않습니다.
#  - task 내부에서 SessionLocal 을 새로 열고 finally 에서 반드시 close 합니다.
#  - idempotent: 이미 active JD 가 있거나 JD_READY/ACTIVE 면 skip (재시도 시 중복 JD 생성 방지).
#  - 로그는 posting_id / detail_url / 상태 / 단계 정도만. (민감정보/HTML/LLM 전문 로그 금지)

# 재시도 대상(일시적 장애) 상세추출 step. 그 외(스킴/SSRF/회사 미검증/인증키 없음 등)는 재시도하지 않습니다.
RETRYABLE_EXTRACT_STEPS = {"fetch_failed", "openai_rate_limited", "openai_network_failed"}


def _parse_skills(text: str) -> list:
    """스킬 텍스트(줄바꿈/콤마 구분)를 리스트로 변환. 빈 항목/공백 제거."""
    return [t.strip() for t in (text or "").replace("\n", ",").split(",") if t.strip()]


def _resolve_user(db, requested_by_user_id):
    """upsert_jd 권한/created_by 용 사용자. 요청자 우선, 없으면 활성 ADMIN fallback. 없으면 None."""
    if requested_by_user_id:
        u = (db.query(User)
             .filter(User.id == requested_by_user_id, User.is_active.is_(True)).first())
        if u:
            return u
    return (db.query(User)
            .filter(User.role_code == "ADMIN", User.is_active.is_(True))
            .order_by(User.id.asc()).first())


@celery_app.task(bind=True, name="app.tasks.job_posting_tasks.analyze_job_posting_jd_task",
                 max_retries=3, default_retry_delay=30)
def analyze_job_posting_jd_task(self, posting_id: int, requested_by_user_id: int = None):
    """posting_id 기준으로 공고 상세를 분석해 JD 를 생성/저장하고 Drive 공고 폴더를 만듭니다.
    상태 전이: (JD_QUEUED) → JD_PROCESSING → JD_READY / JD_FAILED."""
    _log(f"[jd-task] start posting_id={posting_id}")
    db = SessionLocal()
    try:
        posting = db.query(JobPosting).filter(JobPosting.id == posting_id).first()
        if not posting:
            _log(f"[jd-task] posting not found posting_id={posting_id}")
            return {"posting_id": posting_id, "status": "not_found"}
        detail_url = posting.platform_posting_url
        _log(f"[jd-task] posting_id={posting_id} status={posting.status} url={detail_url}")

        # idempotent skip: 이미 active JD 가 있거나 완료 상태
        if (job_posting_service.get_active_jd_entity(db, posting_id) is not None
                or (posting.status or "") in ("JD_READY", "ACTIVE")):
            _log(f"[jd-task] skip (already has active JD / ready) posting_id={posting_id}")
            return {"posting_id": posting_id, "status": "skipped"}

        if not detail_url:
            job_posting_service.mark_jd_lifecycle_status(db, posting_id, "JD_FAILED")
            _log(f"[jd-task] no detail_url posting_id={posting_id}")
            return {"posting_id": posting_id, "status": "JD_FAILED", "step": "detail_url_missing"}

        job_posting_service.mark_jd_lifecycle_status(db, posting_id, "JD_PROCESSING")

        # 1) 상세 URL 분석 — 기존 로직 재사용 (대상 회사 재검증 + LLM JD 구조화)
        try:
            extract = job_extract_service.extract_from_url(detail_url)
        except JobExtractError as e:
            if e.step in RETRYABLE_EXTRACT_STEPS:
                _log(f"[jd-task] extract retryable step={e.step} posting_id={posting_id} retry")
                raise self.retry(exc=e)
            job_posting_service.mark_jd_lifecycle_status(db, posting_id, "JD_FAILED")
            _log(f"[jd-task] extract failed step={e.step} posting_id={posting_id}")
            return {"posting_id": posting_id, "status": "JD_FAILED", "step": e.step}

        if not extract.get("company_verified"):
            job_posting_service.mark_jd_lifecycle_status(db, posting_id, "JD_FAILED")
            _log(f"[jd-task] company not verified posting_id={posting_id}")
            return {"posting_id": posting_id, "status": "JD_FAILED", "step": "company_filter_no_match"}

        user = _resolve_user(db, requested_by_user_id)
        if user is None:
            job_posting_service.mark_jd_lifecycle_status(db, posting_id, "JD_FAILED")
            _log(f"[jd-task] no user for upsert posting_id={posting_id}")
            return {"posting_id": posting_id, "status": "JD_FAILED", "step": "user_not_found"}

        # 2) JD 저장 + Drive 공고 폴더 생성 — 기존 로직 재사용 (자격요건→required, 우대→preferred, 주요업무→jd_content)
        jd_req = JDUpsertRequest(
            title=(extract.get("job_title") or posting.title or None),
            required_skills=_parse_skills(extract.get("qualifications") or ""),
            preferred_skills=_parse_skills(extract.get("preferred") or ""),
            jd_content=extract.get("main_tasks") or None,
        )
        try:
            job_posting_service.upsert_jd(db, user, posting_id, jd_req,
                                          drive_factory=build_authenticated_drive)
        except DriveConfigError as e:
            # Drive 인증은 일시적일 수 있어 재시도. (upsert 는 한 트랜잭션이라 JD 미저장 = 중복 없음)
            _log(f"[jd-task] drive auth failed posting_id={posting_id} type={type(e).__name__} retry")
            raise self.retry(exc=e)
        except HTTPException as e:
            job_posting_service.mark_jd_lifecycle_status(db, posting_id, "JD_FAILED")
            _log(f"[jd-task] jd upsert failed posting_id={posting_id}")
            return {"posting_id": posting_id, "status": "JD_FAILED", "step": "job_jd_upsert_failed"}

        job_posting_service.mark_jd_lifecycle_status(db, posting_id, "JD_READY")
        _log(f"[jd-task] done JD_READY posting_id={posting_id}")
        return {"posting_id": posting_id, "status": "JD_READY"}

    except Retry:
        raise  # self.retry() 는 그대로 전파 (아래 broad except 에서 삼키지 않도록)
    except Exception as e:
        # 재시도 소진(MaxRetriesExceeded) 포함 예상 밖 오류: broad retry 금지, 상태만 JD_FAILED 로 남김.
        try:
            job_posting_service.mark_jd_lifecycle_status(db, posting_id, "JD_FAILED")
        except Exception:
            db.rollback()
        _log(f"[jd-task] unexpected error posting_id={posting_id} type={type(e).__name__}")
        return {"posting_id": posting_id, "status": "JD_FAILED", "step": "unexpected_error"}
    finally:
        db.close()
