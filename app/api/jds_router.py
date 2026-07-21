from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.services import jd_db_service
from app.services.department_access_service import ensure_can_manage_jd
from app.schemas.jd_db_schema import JDCreateRequest, JDUpdateRequest
from app.core.security import get_current_user
from app.db.session import get_db
from app.db.models.user import User

# resume_ai.job_descriptions 기준 JD CRUD 라우터입니다.
# (기존 /api/jd/{dept_id} 도 내부 저장소가 DB 로 전환되었고, 이 라우터는 버전/CRUD 용 확장 API)
#
# ============================= LEGACY =============================
# LEGACY ROUTER — legacy job_descriptions(부서별 JD) 테이블 CRUD (/api/jds).
# 공고 중심 전환으로 신규 개발 대상이 아닙니다. 신규 JD 는 공고별 job_posting_jds
# (POST/PUT /api/job-postings/{id}/jd)를 사용하세요. job_descriptions 테이블에 신규 작성 금지.
# 프론트 런타임 호출 없음. 하위호환 위해 유지 — 동작 변경 금지, 후속 제거 검토(docs/TODO).
# =================================================================

router = APIRouter(prefix="/api/jds", tags=["JD-DB"])


def _error(step: str, message: str, hint: str, status_code: int = 500) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status": "ERROR", "step": step, "error_message": message, "hint": hint},
    )


@router.get("")
def list_jds(dept_id: str):
    """부서의 JD 전체(버전 포함)를 조회합니다."""
    try:
        return {"status": "OK", "dept_id": dept_id, "jds": jd_db_service.list_by_dept(dept_id)}
    except Exception as e:
        return _error("jd_db", f"{type(e).__name__}: {e}", "DB 연결 상태를 확인해주세요.")


@router.get("/active")
def get_active_jd(dept_id: str):
    """부서의 현재 active JD 를 조회합니다."""
    try:
        jd = jd_db_service.get_active(dept_id)
    except Exception as e:
        return _error("jd_db", f"{type(e).__name__}: {e}", "DB 연결 상태를 확인해주세요.")
    if not jd:
        return _error(
            "job_description", "선택한 부서에 등록된 JD가 없습니다.",
            "먼저 JD를 등록해주세요.", status_code=404,
        )
    return {"status": "OK", "jd": jd}


@router.post("")
def create_jd(
    body: JDCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """부서에 새 active JD 를 등록합니다. (기존 active 는 비활성화)"""
    if not body.dept_id:
        return _error("request", "dept_id가 필요합니다.", "부서를 먼저 선택해주세요.", status_code=400)
    # 쓰기 권한 검사(ADMIN 전체 / MANAGER 본인 하위 최하위 부서만). 권한 없으면 HTTPException.
    ensure_can_manage_jd(db, current_user, body.dept_id)
    try:
        jd = jd_db_service.create(
            dept_id=body.dept_id, title=body.title, description=body.description,
            required_skills=body.required_skills, preferred_skills=body.preferred_skills,
            min_years=body.min_years, session=db,
        )
    except Exception as e:
        return _error("jd_db", f"{type(e).__name__}: {e}", "DB 연결 상태를 확인해주세요.")
    return {"status": "OK", "jd": jd}


@router.put("/{jd_id}")
def update_jd(
    jd_id: int,
    body: JDUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """JD 1건을 수정합니다. (수정 대상 JD 의 부서 기준으로 쓰기 권한 검사)"""
    # 수정 대상 JD 의 부서(dept_id) 기준으로 권한을 먼저 확인합니다.
    # (JDUpdateRequest 에는 dept_id 가 없어 부서 변경은 불가하므로 기존 부서만 검사)
    try:
        existing = jd_db_service.get_by_id(jd_id, session=db)
    except Exception as e:
        return _error("jd_db", f"{type(e).__name__}: {e}", "DB 연결 상태를 확인해주세요.")
    if not existing:
        return _error("not_found", f"JD {jd_id} 를 찾을 수 없습니다.", "jd_id 를 확인해주세요.", status_code=404)
    ensure_can_manage_jd(db, current_user, existing["dept_id"])
    try:
        jd = jd_db_service.update(jd_id, body.model_dump(exclude_unset=True), session=db)
    except Exception as e:
        return _error("jd_db", f"{type(e).__name__}: {e}", "DB 연결 상태를 확인해주세요.")
    if not jd:
        return _error("not_found", f"JD {jd_id} 를 찾을 수 없습니다.", "jd_id 를 확인해주세요.", status_code=404)
    return {"status": "OK", "jd": jd}


@router.delete("/{jd_id}")
def delete_jd(
    jd_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """JD 1건을 비활성화(soft delete)합니다. (물리 삭제 아님. 대상 JD 부서 기준 권한 검사)"""
    try:
        existing = jd_db_service.get_by_id(jd_id, session=db)
    except Exception as e:
        return _error("jd_db", f"{type(e).__name__}: {e}", "DB 연결 상태를 확인해주세요.")
    if not existing:
        return _error("not_found", f"JD {jd_id} 를 찾을 수 없습니다.", "jd_id 를 확인해주세요.", status_code=404)
    ensure_can_manage_jd(db, current_user, existing["dept_id"])
    try:
        ok = jd_db_service.deactivate(jd_id, session=db)
    except Exception as e:
        return _error("jd_db", f"{type(e).__name__}: {e}", "DB 연결 상태를 확인해주세요.")
    if not ok:
        return _error("not_found", f"JD {jd_id} 를 찾을 수 없습니다.", "jd_id 를 확인해주세요.", status_code=404)
    return {"status": "OK", "message": f"JD {jd_id} 비활성화 완료", "jd_id": jd_id}
