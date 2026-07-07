from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.user import User
from app.core.security import get_current_user
from app.services import job_posting_service
from app.services import department_access_service
from app.services.google_drive_service import build_authenticated_drive, DriveConfigError, _log
from app.services.jd_recommend_service import recommend_jd
from app.services.openai_llm_service import OpenAILLMError
from app.schemas.job_posting_schema import (
    PostingCreateRequest, PostingUpdateRequest, PostingStatusRequest,
    JDUpsertRequest, PostingResponse, JDResponse,
)

# 공고/JD 관리 라우터. 모든 엔드포인트 로그인 필수(get_current_user).
# 권한은 service 에서 ADMIN 전체 / MANAGER 본인 부서+하위 / VIEWER 조회만 으로 검증합니다.

router = APIRouter(prefix="/api/job-postings", tags=["JobPostings"])


@router.get("")
def list_postings(keyword: str = "", department_id: str = "", platform_code: str = "",
                  status: str = "", jd_status: str = "", date_from: str = "", date_to: str = "",
                  page: int = 1, size: int = 20,
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """권한 범위 내 공고 목록(페이징). 필터(공고명/플랫폼/상태/JD등록/등록일/부서 subtree)는 모두 백엔드에서 적용.

    응답: {"items": [...], "total": N, "page": p, "size": s}. (권한 필터 적용된 total)
    jd_status=ALL/REGISTERED/NOT_REGISTERED. date_from/date_to=등록일 범위(YYYY-MM-DD).
    department_id=해당 부서+하위 부서(권한 밖 403).
    """
    return job_posting_service.list_postings(
        db, current_user,
        keyword=keyword or None, department_id=department_id or None,
        platform_code=platform_code or None, status=status or None, jd_status=jd_status or None,
        date_from=date_from or None, date_to=date_to or None, page=page, size=size,
    )


@router.get("/search", response_model=List[PostingResponse])
def search_postings(keyword: str = "",
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """공고 선택용 경량 검색(이력서 등록/분석/현황의 공고 선택 UI). 권한 범위 내."""
    return job_posting_service.search_postings(db, current_user, keyword=keyword or None)


@router.get("/dept-search")
def dept_search(keyword: str = "",
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """공고 등록용 부서/팀 검색. 권한 범위 내(ADMIN 전체 / MANAGER·VIEWER 본인 부서+하위).

    응답은 사용자 관리 부서검색과 동일: [{id, name, parent_id, path, is_leaf}].
    """
    return department_access_service.search_accessible_departments(db, current_user, keyword)


@router.get("/{posting_id}", response_model=PostingResponse)
def get_posting(posting_id: int,
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return job_posting_service.get_posting(db, current_user, posting_id)


@router.post("", response_model=PostingResponse)
def create_posting(body: PostingCreateRequest,
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """공고 등록(VIEWER 불가, MANAGER 는 본인 부서+하위만). JD 상세는 필수 아님.

    공고 등록 시점에는 Drive 폴더를 만들지 않습니다(JD 미등록 상태).
    공고 Drive 폴더는 'JD 등록 완료 시점'에 생성합니다(POST/PUT /{id}/jd).
    """
    return job_posting_service.create_posting(db, current_user, body)


@router.put("/{posting_id}", response_model=PostingResponse)
def update_posting(posting_id: int, body: PostingUpdateRequest,
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return job_posting_service.update_posting(db, current_user, posting_id, body)


@router.patch("/{posting_id}/status", response_model=PostingResponse)
def set_status(posting_id: int, body: PostingStatusRequest,
               current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return job_posting_service.set_status(db, current_user, posting_id, body.status)


@router.get("/{posting_id}/jd")
def get_jd(posting_id: int,
           current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """공고의 현재 active JD. 없으면 {"jd": null} (JD 미등록)."""
    return {"jd": job_posting_service.get_jd(db, current_user, posting_id)}


def _upsert_jd_with_drive(db, current_user, posting_id, body):
    """JD 저장 + (폴더 없으면) Drive 공고 폴더 생성. Drive 실패 시 JD 저장도 롤백되어 실패 처리."""
    try:
        return job_posting_service.upsert_jd(
            db, current_user, posting_id, body, drive_factory=build_authenticated_drive)
    except HTTPException:
        raise
    except DriveConfigError as e:
        _log(f"[posting-jd] Drive 인증 실패: {type(e).__name__}: {e}")
        raise HTTPException(status_code=503,
                            detail="Google Drive 인증이 필요해 공고 폴더를 만들 수 없습니다. JD 저장을 취소했습니다.")
    except Exception as e:
        _log(f"[posting-jd] JD 저장/Drive 폴더 생성 실패(롤백): {type(e).__name__}: {e}")
        raise HTTPException(status_code=502,
                            detail="JD 저장 또는 공고 Drive 폴더 생성에 실패했습니다. 잠시 후 다시 시도해주세요.")


@router.post("/{posting_id}/jd", response_model=JDResponse)
def create_jd(posting_id: int, body: JDUpsertRequest,
              current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """JD 등록(upsert). JD 저장 성공 시 공고 Drive 폴더가 없으면 생성합니다."""
    return _upsert_jd_with_drive(db, current_user, posting_id, body)


@router.put("/{posting_id}/jd", response_model=JDResponse)
def update_jd(posting_id: int, body: JDUpsertRequest,
              current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """JD 수정(upsert). 공고 Drive 폴더가 이미 있으면 재생성하지 않습니다(멱등)."""
    return _upsert_jd_with_drive(db, current_user, posting_id, body)


@router.post("/{posting_id}/jd/recommend")
def recommend_posting_jd(posting_id: int,
                         current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """공고명/부서명 기반으로 OpenAI 가 JD 초안을 추천합니다. (DB 저장 안 함 — 프론트 입력란 채우기용)

    권한: ADMIN 전체 / MANAGER 본인 부서+하위 / VIEWER 403 (ensure_can_manage_posting).
    기존 jd_recommend_service.recommend_jd 를 재사용합니다(점수 산식/추천 기준과 무관).
    """
    posting = job_posting_service.get_posting_entity(db, posting_id)
    job_posting_service.ensure_can_manage_posting(db, current_user, posting)
    dept_name = job_posting_service.posting_dept_name(db, posting)
    position_title = (posting.title or "").strip() or f"{dept_name} 채용 포지션"
    try:
        data = recommend_jd(dept_name, position_title)
    except OpenAILLMError as e:
        return JSONResponse(status_code=400, content={
            "status": "ERROR", "step": e.step, "error_message": e.message, "hint": e.hint})
    except Exception as e:
        _log(f"[posting-jd-recommend] 실패: {type(e).__name__}: {e}")
        return JSONResponse(status_code=500, content={
            "status": "ERROR", "step": "jd_recommend",
            "error_message": "추천 JD 생성 중 오류가 발생했습니다.", "hint": "잠시 후 다시 시도해주세요."})
    return {"status": "OK", "source": "openai", "data": {
        "title": position_title,
        "required_skills": data["required_skills"],
        "preferred_skills": data["preferred_skills"],
        "jd_content": data["description"],
    }}
