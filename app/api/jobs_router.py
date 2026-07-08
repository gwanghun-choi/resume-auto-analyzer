from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.db.models.user import User
from app.services import job_extract_service, job_posting_discovery_service
from app.services.job_extract_service import JobExtractError
from app.services.saramin_job_collect_service import SaraminCollectError
from app.services.jobkorea_job_collect_service import JobKoreaCollectError
from app.services.google_drive_service import _log
from app.schemas.job_posting_schema import JobExtractRequest

# 공고 URL 기반 자동 채우기 라우터. (공고/JD 관리 팝업의 [공고 내용 가져오기] 버튼)
# 결과는 화면 입력값 자동 채우기 용도로만 반환하며, DB 저장/부서 자동선택은 하지 않습니다.

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])


@router.post("/extract-from-url")
def extract_from_url(body: JobExtractRequest,
                     current_user: User = Depends(get_current_user)):
    """
    공고 URL 페이지를 가져와 (디딤(주) 공고 검증 후) LLM 으로 공고명/플랫폼/주요업무/자격요건/우대사항을 추출합니다.
    - 권한: 공고/JD 등록·수정 권한자(ADMIN/MANAGER)만. VIEWER 403. (URL 조회/LLM 호출 전에 검사)
    - 디딤(주) 공고가 아니면 company_verified=false 로 반환(LLM 미호출, 입력값 미변경).
    """
    # 권한 검사 — URL 조회/LLM 호출 전에 수행
    role = (current_user.role_code or "").upper()
    if role not in ("ADMIN", "MANAGER"):
        raise HTTPException(status_code=403, detail="공고 자동 추출 권한이 없습니다.")

    url = (body.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="공고 URL을 입력해주세요.")

    try:
        return job_extract_service.extract_from_url(url)
    except JobExtractError as e:
        # SSRF/스킴/HTML 아님 등은 400, 네트워크/LLM 실패는 502/500. 민감정보는 메시지에 포함하지 않음.
        _log(f"[job-extract] error step={e.step} status={e.status_code}")
        return JSONResponse(
            status_code=e.status_code,
            content={"status": "ERROR", "step": e.step,
                     "error_message": e.message, "hint": e.hint},
        )
    except Exception as e:
        _log(f"[job-extract] unexpected error type={type(e).__name__}")
        return JSONResponse(
            status_code=500,
            content={"status": "ERROR", "step": "job_extract_failed",
                     "error_message": "공고 내용을 가져오지 못했습니다.",
                     "hint": "URL을 확인하거나 직접 입력해주세요."},
        )


@router.post("/discover/saramin/didim")
def discover_saramin_didim(dry_run: bool = False,
                           current_user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """사람인 '디딤' 검색 결과에서 디딤(주) 신규 공고를 수집·등록하고 JD 분석을 큐에 넣습니다(수동 실행).

    - 권한: ADMIN/MANAGER 만(VIEWER 403). 스케줄러(자동 1시간 주기)는 코드상 주석 처리 상태입니다.
    - 흐름: 검색결과 수집 → 디딤(주) 필터 → detail_url 중복 확인 → 신규만 공고 insert(DRAFT)
            → JD 분석 task enqueue(posting_id) → 공고 상태 JD_QUEUED.
      실제 상세 URL 분석/JD 저장/Drive 폴더 생성은 **Celery worker** 가 비동기로 수행합니다
      (job_extract_service / job_posting_service 재사용).
    - 공고 하나가 실패해도 나머지는 계속 처리하며, 결과 요약(collected/matched/new/queued/duplicate/failed)을 반환합니다.
    - dry_run=true 면 실제 insert/큐 적재 없이 수집·중복 판단 결과만 반환합니다(검증용).
    """
    role = (current_user.role_code or "").upper()
    if role not in ("ADMIN", "MANAGER"):
        raise HTTPException(status_code=403, detail="공고 자동 수집 권한이 없습니다.")
    try:
        return job_posting_discovery_service.discover_saramin_didim(db, current_user, dry_run=dry_run)
    except SaraminCollectError as e:
        # 검색 페이지 fetch/parse 실패 등 수집 자체 실패. 민감정보는 메시지에 포함하지 않음.
        _log(f"[saramin-discovery] collect error step={e.step} status={e.status_code}")
        return JSONResponse(
            status_code=e.status_code,
            content={"status": "ERROR", "step": e.step,
                     "error_message": e.message, "hint": e.hint},
        )
    except Exception as e:
        _log(f"[saramin-discovery] unexpected error type={type(e).__name__}")
        return JSONResponse(
            status_code=500,
            content={"status": "ERROR", "step": "saramin_discovery_failed",
                     "error_message": "사람인 공고 수집 중 오류가 발생했습니다.",
                     "hint": "잠시 후 다시 시도해주세요."},
        )


@router.post("/discover/jobkorea/didim")
def discover_jobkorea_didim(dry_run: bool = False,
                            current_user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """잡코리아 '디딤(주)' 검색 결과에서 디딤(주) 신규 공고를 수집·등록하고 JD 분석을 큐에 넣습니다(수동 실행).

    사람인과 동일한 등록/큐 로직을 재사용하며 platform_code=JOBKOREA 로 저장됩니다.
    잡코리아 검색 결과는 서버 렌더링(SSR)이라 정적 HTML 로 수집합니다(Playwright 미사용).
    dry_run=true 면 실제 insert/큐 적재 없이 수집·중복 판단 결과만 반환합니다(검증용).
    """
    role = (current_user.role_code or "").upper()
    if role not in ("ADMIN", "MANAGER"):
        raise HTTPException(status_code=403, detail="공고 자동 수집 권한이 없습니다.")
    try:
        return job_posting_discovery_service.discover_jobkorea_didim(db, current_user, dry_run=dry_run)
    except JobKoreaCollectError as e:
        _log(f"[jobkorea-discovery] collect error step={e.step} status={e.status_code}")
        return JSONResponse(
            status_code=e.status_code,
            content={"status": "ERROR", "step": e.step,
                     "error_message": e.message, "hint": e.hint},
        )
    except Exception as e:
        _log(f"[jobkorea-discovery] unexpected error type={type(e).__name__}")
        return JSONResponse(
            status_code=500,
            content={"status": "ERROR", "step": "jobkorea_discovery_failed",
                     "error_message": "잡코리아 공고 수집 중 오류가 발생했습니다.",
                     "hint": "잠시 후 다시 시도해주세요."},
        )
