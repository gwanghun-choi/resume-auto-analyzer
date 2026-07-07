from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas.analysis_response import AnalyzeResponse
from app.services.jd_service import JDService
from app.services.batch_service import BatchService
from app.services.department_access_service import ensure_can_run_analysis
from app.core.security import get_current_user
from app.db.session import get_db
from app.db.models.user import User

# ============================= LEGACY =============================
# LEGACY ROUTER — 부서 + 업로드ID 기준 배치 분석 API (/api/analyze), legacy batch_service/jd_service 사용.
# 공고 중심 전환으로 신규 개발 대상이 아닙니다. 신규/비동기(Celery) 분석은 공고 기준
# POST /api/resumes/analyze-posting (resume_analysis_service.analyze_posting)만 사용하세요.
# 프론트 런타임 호출 없음(app.js 헤더 주석에만 존재). 하위호환 위해 유지 — 동작 변경 금지, 후속 제거 검토(docs/TODO).
# =================================================================

router = APIRouter(prefix="/api/analyze", tags=["Analyze"])


def get_jd_service():
    return JDService()


def get_batch_service():
    return BatchService()


@router.post("/{dept_id}/{upload_id}", response_model=AnalyzeResponse)
def analyze(
    dept_id: str,
    upload_id: str,
    jd_service: JDService = Depends(get_jd_service),
    batch_service: BatchService = Depends(get_batch_service),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    1. 해당 팀의 JD 를 읽고
    2. upload_id 에 해당하는 업로드 파일들을 찾아
    3. 파일별로 텍스트 추출 -> AI 분석 -> 매칭 점수 계산
    을 수행한 뒤 결과 리스트를 반환합니다. (결과 JSON 도 함께 저장)
    (분석 실행 권한: ADMIN 전체 / MANAGER 본인 하위 / VIEWER 불가 — 분석 실행 전에 검사)
    """
    ensure_can_run_analysis(db, current_user, dept_id)
    jd = jd_service.get(dept_id)
    results = batch_service.analyze_upload(jd, dept_id, upload_id)
    return AnalyzeResponse(dept_id=dept_id, upload_id=upload_id, results=results)
