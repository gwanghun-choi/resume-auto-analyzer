from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.job_posting import JobPosting
from app.schemas.job_posting_schema import PostingCreateRequest
from app.services import job_posting_service, saramin_job_collect_service
from app.services.google_drive_service import _log
from app.tasks.job_posting_tasks import analyze_job_posting_jd_task

# 사람인 검색 결과에서 찾은 디딤(주) 공고 중 '신규' 만 골라 job_postings 에 등록하고,
# JD 분석 작업(상세 URL 분석 + JD 저장 + Drive 폴더)은 Celery worker 로 넘깁니다(비동기).
#
# 정책:
#  - 큐에는 detail_url 이 아니라 posting_id 를 넣습니다(worker 가 DB 에서 다시 조회 — 중복/상태/실패 처리 용이).
#  - 공고 하나가 실패해도 전체 배치가 중단되지 않도록 공고 단위 try/except 로 격리합니다.
#  - 신규 공고 상태 기본값은 DRAFT(자동 수집분 = 검토 전), 부서/팀은 미지정(None). enqueue 후 JD_QUEUED.
#  - 중복 판단은 현재 모델의 URL 컬럼(platform_posting_url) 기준(별도 external_id 컬럼 미추가).

PLATFORM_CODE = "SARAMIN"
DEFAULT_STATUS = "DRAFT"   # 자동 수집 공고 초기 상태 (VALID_STATUS: DRAFT/OPEN/CLOSED/INACTIVE)


def _find_existing(db: Session, detail_url: str, rec_idx: str):
    """detail_url(정규화) 또는 rec_idx 기준 기존 공고 조회. 있으면 id 반환, 없으면 None.
    (과거에 tracking query 가 붙은 URL 로 저장된 경우까지 잡도록 rec_idx LIKE 도 함께 확인)"""
    cond = JobPosting.platform_posting_url == detail_url
    if rec_idx:
        cond = or_(cond, JobPosting.platform_posting_url.ilike(f"%rec_idx={rec_idx}%"))
    row = db.query(JobPosting.id).filter(cond).first()
    return row[0] if row else None


def _register_one(db: Session, user, item: dict) -> dict:
    """공고 1건 처리: 중복 확인 → 신규면 공고 insert(DRAFT) → JD 분석 task enqueue(posting_id) → JD_QUEUED.
    상세 분석/JD 저장/Drive 폴더는 worker 가 수행합니다. 결과 dict 반환, 예외는 호출측에서 격리."""
    detail_url = item["detail_url"]
    result = {"title": item.get("title") or "", "detail_url": detail_url, "rec_idx": item.get("rec_idx")}

    # 1) 중복 확인 (external_id 성격의 rec_idx / 정규화 URL). 이미 있으면 task 중복 enqueue 하지 않음.
    existing_id = _find_existing(db, detail_url, item.get("rec_idx"))
    if existing_id:
        result.update(status="duplicate", step="duplicate_job_posting", posting_id=existing_id)
        return result

    title = (item.get("title") or "").strip() or "(제목 미상)"
    result["title"] = title

    # 2) 공고 insert (부서 미지정, 상태 DRAFT). create_posting 이 자체 commit.
    try:
        posting = job_posting_service.create_posting(db, user, PostingCreateRequest(
            title=title,
            department_id=None,
            platform_code=PLATFORM_CODE,
            platform_posting_url=detail_url,
            status=DEFAULT_STATUS,
        ))
    except HTTPException as e:
        result.update(status="failed", step="job_posting_insert_failed", error=str(e.detail))
        return result
    posting_id = posting["id"]
    result["posting_id"] = posting_id

    # 3) JD 분석 작업 enqueue. race 방지 위해 delay() 전에 JD_QUEUED 를 먼저 기록합니다
    #    (worker 가 JD_PROCESSING 으로 바꾸기 전에 JD_QUEUED 가 확정됨).
    job_posting_service.mark_jd_lifecycle_status(db, posting_id, "JD_QUEUED")
    try:
        analyze_job_posting_jd_task.delay(posting_id, getattr(user, "id", None))
    except Exception as e:
        # broker(Redis) 연결 실패 등으로 큐 적재 실패 → 공고는 유지하고 상태만 JD_FAILED.
        _log(f"[saramin-discovery] enqueue 실패 posting_id={posting_id} type={type(e).__name__}")
        job_posting_service.mark_jd_lifecycle_status(db, posting_id, "JD_FAILED")
        result.update(status="enqueue_failed", step="task_enqueue_failed")
        return result

    result.update(status="JD_QUEUED", step=None)
    return result


def discover_saramin_didim(db: Session, user, search_url: str = None) -> dict:
    """사람인 '디딤' 검색 → 디딤(주) 신규 공고 insert + JD 분석 task enqueue(수동 API/스케줄러 공통 진입점).

    반환: 처리 결과 요약(collected/matched/new/queued/duplicate/failed 카운트 + 항목별 상태).
    수집 자체 실패(SaraminCollectError)는 호출측으로 전파, 공고 단위 실패는 격리해 카운트만 집계.
    """
    company_filter = settings.SARAMIN_DIDIM_COMPANY_NAME
    collected = saramin_job_collect_service.collect_didim_postings(search_url)
    items = collected["items"]

    _log(f"[saramin-discovery] start search_url={collected['search_url']} "
         f"collected={collected['collected_count']} matched_didim={len(items)}")

    out_items = []
    new_count = queued_count = dup_count = failed_count = 0
    for it in items:
        try:
            r = _register_one(db, user, it)
        except Exception as e:
            # 예상 못한 오류도 공고 단위로 격리 (전체 배치 중단 금지). 민감정보/HTML 은 로그 금지.
            _log(f"[saramin-discovery] unexpected error rec_idx={it.get('rec_idx')} type={type(e).__name__}")
            r = {"title": it.get("title") or "", "detail_url": it["detail_url"],
                 "rec_idx": it.get("rec_idx"), "status": "failed", "step": "unexpected_error"}
        status = r.get("status")
        if status == "JD_QUEUED":
            new_count += 1
            queued_count += 1
        elif status == "duplicate":
            dup_count += 1
        elif status == "enqueue_failed":
            new_count += 1          # 공고는 insert 됨(큐 적재만 실패)
            failed_count += 1
            _log(f"[saramin-discovery] item enqueue_failed url={r['detail_url']}")
        else:
            failed_count += 1
            _log(f"[saramin-discovery] item failed step={r.get('step')} url={r['detail_url']}")
        out_items.append(r)

    summary = {
        "source": PLATFORM_CODE,
        "keyword": settings.SARAMIN_DIDIM_KEYWORD,
        "company_filter": company_filter,
        "search_url": collected["search_url"],
        "collected_count": collected["collected_count"],
        "matched_company_count": len(items),
        "new_count": new_count,
        "queued_count": queued_count,
        "skipped_duplicate_count": dup_count,
        "failed_count": failed_count,
        "items": out_items,
    }
    _log(f"[saramin-discovery] done collected={summary['collected_count']} "
         f"matched={summary['matched_company_count']} new={new_count} queued={queued_count} "
         f"dup={dup_count} failed={failed_count}")
    return summary
