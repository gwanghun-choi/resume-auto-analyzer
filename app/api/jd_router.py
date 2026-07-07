from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.schemas.jd_schema import JD, JDSaveRequest, JDRecommendRequest
from app.services.jd_service import JDService
from app.services.jd_recommend_service import recommend_jd
from app.services.openai_llm_service import OpenAILLMError
from app.services.department_access_service import ensure_can_manage_jd
from app.core.security import get_current_user
from app.db.session import get_db
from app.db.models.user import User

# ============================= LEGACY =============================
# LEGACY ROUTER — 부서(팀) 기준 JD 조회/저장 API (/api/jd), legacy job_descriptions 기반(jd_service).
# 공고 중심 전환으로 신규 개발 대상이 아닙니다. 신규 JD 는 공고별 job_posting_jds
# (POST/PUT /api/job-postings/{id}/jd, job_posting_service.upsert_jd)를 사용하세요.
# 프론트의 이 API 를 쓰는 JD 화면(view-jd)은 메뉴에 연결되어 있지 않아 도달 불가(orphaned).
# 하위호환 위해 유지 — 동작 변경 금지, 후속 제거 검토(docs/TODO).
# =================================================================

router = APIRouter(prefix="/api/jd", tags=["JD"])


def get_jd_service():
    return JDService()


def _recommend_error(step: str, message: str, hint: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status": "ERROR", "step": step,
                 "error_message": message, "hint": hint},
    )


# 주의: 경로 매칭 순서상 /recommend 를 /{dept_id} 보다 먼저 선언합니다.
@router.post("/recommend")
def recommend_jd_route(body: JDRecommendRequest):
    """
    선택 부서명/포지션명을 기반으로 OpenAI 에게 JD 초안을 요청합니다.
    DB 저장은 하지 않으며, 결과는 프론트 입력란 채우기에만 사용됩니다.
    """
    dept_name = (body.dept_name or "").strip()
    if not dept_name and not (body.dept_id or "").strip():
        return _recommend_error("dept_required", "선택된 부서가 없습니다.", "먼저 부서/팀을 선택해주세요.")
    # 포지션명이 비어 있으면 '{부서명} 채용 포지션'으로 구성합니다.
    position_title = (body.position_title or "").strip() or f"{dept_name} 채용 포지션"
    try:
        data = recommend_jd(dept_name, position_title)
    except OpenAILLMError as e:
        # OpenAI 인증/호출/파싱 실패 → 실제 step 그대로 반환 (openai_api_key_missing 등)
        return _recommend_error(e.step, e.message, e.hint)
    except Exception:
        return _recommend_error(
            "jd_recommend", "추천 JD 생성 중 오류가 발생했습니다.",
            "선택 부서와 포지션명을 확인한 뒤 다시 시도해주세요.", 500,
        )
    return {"status": "OK", "source": "openai",
            "data": {"position_title": position_title, **data}}


@router.get("/{dept_id}", response_model=JD)
def get_jd(dept_id: str, service: JDService = Depends(get_jd_service)):
    """
    선택한 팀의 JD 를 조회합니다.
    저장된 JD 가 없으면 기본 JD 템플릿을 반환합니다.
    """
    return service.get(dept_id)


@router.post("/{dept_id}", response_model=JD)
def save_jd(
    dept_id: str,
    req: JDSaveRequest,
    service: JDService = Depends(get_jd_service),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    선택한 팀의 JD 를 저장합니다.
    DB 가 없으므로 로컬 JSON 파일(data/config/jd/{dept_id}.json)에 저장합니다.
    (쓰기 권한: ADMIN 전체 / MANAGER 본인 하위 최하위 부서만 — ensure_can_manage_jd)
    """
    ensure_can_manage_jd(db, current_user, dept_id)
    return service.save(dept_id, req)
