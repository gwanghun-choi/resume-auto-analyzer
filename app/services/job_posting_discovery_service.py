from fastapi import HTTPException
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.job_posting import JobPosting
from app.schemas.job_posting_schema import PostingCreateRequest
from app.services import (
    job_posting_service, saramin_job_collect_service, jobkorea_job_collect_service,
)
from app.services.google_drive_service import _log
from app.tasks.job_posting_tasks import analyze_job_posting_jd_task

# 채용 플랫폼(사람인/잡코리아) 검색 결과에서 찾은 디딤(주) 공고 중 '신규' 만 골라 job_postings 에 등록하고,
# JD 분석 작업(상세 URL 분석 + JD 저장 + Drive 폴더)은 Celery worker 로 넘깁니다(비동기).
#
# 정책:
#  - 큐에는 detail_url 이 아니라 posting_id 를 넣습니다(worker 가 DB 에서 다시 조회 — 중복/상태/실패 처리 용이).
#  - 공고 하나가 실패해도 전체 배치가 중단되지 않도록 공고 단위 try/except 로 격리합니다.
#  - 신규 공고 상태 기본값은 DRAFT(자동 수집분 = 검토 전), 부서/팀은 미지정(None). enqueue 후 JD_QUEUED.
#  - 중복 판단은 현재 모델의 URL 컬럼(platform_posting_url) 기준(별도 external_id 컬럼 미추가).
#    같은 공고가 tracking parameter 만 다르게 들어와도, 수집기가 만든 normalized(canonical) URL 로 비교하므로
#    중복 insert 되지 않습니다. plus platform_code 로 스코프해 플랫폼 간 id 충돌을 방지합니다.
#  - 사람인/잡코리아는 같은 등록/큐 로직(_register_one)을 공유합니다(복붙 금지).

DEFAULT_STATUS = "DRAFT"   # 자동 수집 공고 초기 상태 (VALID_STATUS: DRAFT/OPEN/CLOSED/INACTIVE)


def _fuzzy_token(platform_code: str, rec_idx: str) -> str:
    """과거에 tracking query 가 붙은 raw URL 로 저장된 레코드까지 잡기 위한 URL 부분 문자열.
    플랫폼별 공고 식별자 표기(사람인 rec_idx= / 잡코리아 GI_Read/)에 맞춥니다."""
    if platform_code == "JOBKOREA":
        return f"GI_Read/{rec_idx}"
    return f"rec_idx={rec_idx}"   # SARAMIN


def _find_existing(db: Session, platform_code: str, detail_url: str, rec_idx: str):
    """normalized detail_url(정확) 또는 platform_code+공고식별자(부분일치) 기준 기존 공고 조회.
    있으면 id, 없으면 None. (1순위 platform_code+식별자, 2순위 normalized_url 개념을 한 쿼리로 처리)"""
    cond = JobPosting.platform_posting_url == detail_url
    if rec_idx:
        cond = or_(cond, and_(
            JobPosting.platform_code == platform_code,
            JobPosting.platform_posting_url.ilike(f"%{_fuzzy_token(platform_code, rec_idx)}%"),
        ))
    row = db.query(JobPosting.id).filter(cond).first()
    return row[0] if row else None


def _register_one(db: Session, user, item: dict, platform_code: str) -> dict:
    """공고 1건 처리: 중복 확인 → 신규면 공고 insert(DRAFT) → JD 분석 task enqueue(posting_id) → JD_QUEUED.
    상세 분석/JD 저장/Drive 폴더는 worker 가 수행합니다. 결과 dict 반환, 예외는 호출측에서 격리."""
    detail_url = item["detail_url"]
    result = {"title": item.get("title") or "", "detail_url": detail_url, "rec_idx": item.get("rec_idx")}

    # 1) 중복 확인 (external_id 성격의 rec_idx / 정규화 URL). 이미 있으면 task 중복 enqueue 하지 않음.
    existing_id = _find_existing(db, platform_code, detail_url, item.get("rec_idx"))
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
            platform_code=platform_code,
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
        _log(f"[{platform_code.lower()}-discovery] enqueue 실패 posting_id={posting_id} type={type(e).__name__}")
        job_posting_service.mark_jd_lifecycle_status(db, posting_id, "JD_FAILED")
        result.update(status="enqueue_failed", step="task_enqueue_failed")
        return result

    result.update(status="JD_QUEUED", step=None)
    return result


def _dry_run_items(db: Session, platform_code: str, items: list) -> list:
    """실제 insert/enqueue 없이 각 항목의 수집/중복 판단 결과만 만들어 반환합니다.
    항목별: platform_code / company_name / title / raw_url / normalized_url / is_duplicate / skip_reason."""
    out = []
    for it in items:
        existing_id = _find_existing(db, platform_code, it["detail_url"], it.get("rec_idx"))
        out.append({
            "platform_code": platform_code,
            "company_name": it.get("company_name"),
            "title": it.get("title") or "",
            "raw_url": it.get("raw_url") or it["detail_url"],
            "normalized_url": it["detail_url"],
            "rec_idx": it.get("rec_idx"),
            "is_duplicate": existing_id is not None,
            "skip_reason": "duplicate_job_posting" if existing_id else None,
        })
    return out


def _discover(db: Session, user, platform_code: str, collected: dict,
              keyword: str, company_filter: str, dry_run: bool = False) -> dict:
    """수집 결과(collected)를 받아 신규 공고 등록 + JD 분석 enqueue(또는 dry-run) 후 요약을 반환합니다.
    (사람인/잡코리아 공통 코어. 수집기별 진입 함수가 collected 를 넘겨 재사용합니다.)"""
    items = collected["items"]
    _log(f"[{platform_code.lower()}-discovery] start search_url={collected['search_url']} "
         f"collected={collected['collected_count']} matched_didim={len(items)} dry_run={dry_run}")

    if dry_run:
        dr_items = _dry_run_items(db, platform_code, items)
        dup = sum(1 for r in dr_items if r["is_duplicate"])
        summary = {
            "source": platform_code, "dry_run": True, "keyword": keyword,
            "company_filter": company_filter, "search_url": collected["search_url"],
            "collected_count": collected["collected_count"], "matched_company_count": len(items),
            "new_count": len(dr_items) - dup, "queued_count": 0,
            "skipped_duplicate_count": dup, "failed_count": 0, "items": dr_items,
        }
        _log(f"[{platform_code.lower()}-discovery] dry-run done matched={len(items)} "
             f"new={summary['new_count']} dup={dup}")
        return summary

    out_items = []
    new_count = queued_count = dup_count = failed_count = 0
    for it in items:
        try:
            r = _register_one(db, user, it, platform_code)
        except Exception as e:
            # 예상 못한 오류도 공고 단위로 격리 (전체 배치 중단 금지). 민감정보/HTML 은 로그 금지.
            _log(f"[{platform_code.lower()}-discovery] unexpected error rec_idx={it.get('rec_idx')} type={type(e).__name__}")
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
            _log(f"[{platform_code.lower()}-discovery] item enqueue_failed url={r['detail_url']}")
        else:
            failed_count += 1
            _log(f"[{platform_code.lower()}-discovery] item failed step={r.get('step')} url={r['detail_url']}")
        out_items.append(r)

    summary = {
        "source": platform_code,
        "dry_run": False,
        "keyword": keyword,
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
    _log(f"[{platform_code.lower()}-discovery] done collected={summary['collected_count']} "
         f"matched={summary['matched_company_count']} new={new_count} queued={queued_count} "
         f"dup={dup_count} failed={failed_count}")
    return summary


def discover_saramin_didim(db: Session, user, search_url: str = None, dry_run: bool = False) -> dict:
    """사람인 '디딤' 검색 → 디딤(주) 신규 공고 insert + JD 분석 task enqueue(수동 API/스케줄러 공통 진입점).

    반환: 처리 결과 요약(collected/matched/new/queued/duplicate/failed 카운트 + 항목별 상태).
    수집 자체 실패(SaraminCollectError)는 호출측으로 전파, 공고 단위 실패는 격리해 카운트만 집계.
    dry_run=True 면 실제 insert/enqueue 없이 수집·중복 판단 결과만 반환합니다.
    """
    collected = saramin_job_collect_service.collect_didim_postings(search_url)
    return _discover(db, user, "SARAMIN", collected,
                     settings.SARAMIN_DIDIM_KEYWORD, settings.SARAMIN_DIDIM_COMPANY_NAME, dry_run)


def discover_jobkorea_didim(db: Session, user, search_url: str = None, dry_run: bool = False) -> dict:
    """잡코리아 '디딤(주)' 검색 → 디딤(주) 신규 공고 insert + JD 분석 task enqueue(수동 API/스케줄러 공통 진입점).

    사람인과 동일한 등록/큐 로직(_register_one)을 재사용합니다. platform_code=JOBKOREA 로 저장됩니다.
    dry_run=True 면 실제 insert/enqueue 없이 수집·중복 판단 결과만 반환합니다.
    """
    collected = jobkorea_job_collect_service.collect_didim_postings(search_url)
    return _discover(db, user, "JOBKOREA", collected,
                     settings.JOBKOREA_DIDIM_KEYWORD, settings.JOBKOREA_DIDIM_COMPANY_NAME, dry_run)
