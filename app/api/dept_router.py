from fastapi import APIRouter, Depends
from typing import List

from app.schemas.dept_schema import Dept
from app.services.dept_service import DeptService

# ============================= LEGACY =============================
# LEGACY ROUTER — 부서(department) 기준 더미 부서 목록 API (/api/depts).
# 공고 중심 전환으로 신규 개발 대상이 아닙니다. New code must use the job-posting flow
# (부서 조회는 department_access_service / GET /api/job-postings/dept-search).
# 프론트 런타임 호출 없음(app.js 헤더 주석에만 존재). 하위호환 위해 유지 — 동작 변경 금지, 후속 제거 검토(docs/TODO).
# =================================================================

router = APIRouter(prefix="/api/depts", tags=["Dept"])


def get_dept_service():
    # Spring 의 @Autowired 와 비슷한 의존성 주입입니다.
    return DeptService()


@router.get("", response_model=List[Dept])
def get_depts(service: DeptService = Depends(get_dept_service)):
    """
    더미 부서 목록을 flat list 로 반환합니다.
    화면(app.js)에서 parent_id 기준으로 트리로 변환합니다.
    """
    return service.get_all()
