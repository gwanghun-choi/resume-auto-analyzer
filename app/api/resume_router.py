import json
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from typing import List
from app.schemas.resume_schema import ResumeAnalysisResponse
from app.services.resume_parser_service import ResumeParserService
from app.services.ai_agent_service import AiAgentService
from app.services.matching_service import MatchingService

# ============================= LEGACY =============================
# LEGACY ROUTER — 단일 파일 즉시 분석 API (/api/resume/analyze). (인증 없음 — 정리 대상)
# 공고 중심 전환으로 신규 개발 대상이 아닙니다. 신규 분석은 공고 기준
# POST /api/resumes/analyze-posting (resume_analysis_service.analyze_posting)를 사용하세요.
# 프론트 런타임 호출 없음. 하위호환 위해 유지 — 동작 변경 금지, 후속 제거 검토(docs/TODO).
# =================================================================

router = APIRouter(prefix="/api/resume", tags=["Resume"])

# 의존성 주입 (Dependency Injection) - Spring의 @Autowired와 유사한 개념입니다.
def get_parser_service():
    return ResumeParserService()

def get_ai_service():
    return AiAgentService()

def get_matching_service():
    return MatchingService()

@router.post("/analyze", response_model=ResumeAnalysisResponse)
async def analyze_resume(
    position: str = Form(..., description="지원 포지션명"),
    required_skills: str = Form(..., description="필수 기술 스택 (쉼표로 구분)"),
    preferred_skills: str = Form(..., description="우대 기술 스택 (쉼표로 구분)"),
    file: UploadFile = File(..., description="이력서 파일 (PDF, DOCX)"),
    parser: ResumeParserService = Depends(get_parser_service),
    ai_service: AiAgentService = Depends(get_ai_service),
    matcher: MatchingService = Depends(get_matching_service)
):
    """
    이력서 파일을 업로드받아 AI 분석 및 매칭 점수를 산출합니다.
    """
    # 1. 파일 존재 여부 확인
    if not file:
        raise HTTPException(status_code=400, detail="파일이 업로드되지 않았습니다.")

    # 2. 리스트 변환 (쉼표 구분 문자열 -> 리스트)
    req_skills_list = [s.strip() for s in required_skills.split(",") if s.strip()]
    pref_skills_list = [s.strip() for s in preferred_skills.split(",") if s.strip()]

    # 3. 텍스트 추출 (Parsing)
    file_content = await file.read()
    resume_text = parser.parse_resume(file_content, file.filename)

    # 4. AI 분석 (OpenAI)
    ai_result = ai_service.analyze(
        resume_text=resume_text,
        position=position,
        required_skills=req_skills_list,
        preferred_skills=pref_skills_list
    )

    # 5. 매칭 점수 계산 (Matching Service)
    match_result = matcher.calculate_match(
        extracted_skills=ai_result.get("extracted_skills", []),
        required_skills=req_skills_list,
        preferred_skills=pref_skills_list,
        ai_judgment_score=ai_result.get("ai_judgment_score", 0)
    )

    # 6. 결과 조합하여 반환 (DTO에 매핑)
    return ResumeAnalysisResponse(
        candidate_summary=ai_result.get("candidate_summary", ""),
        extracted_skills=ai_result.get("extracted_skills", []),
        career_summary=ai_result.get("career_summary", ""),
        match_score=match_result["match_score"],
        matched_required_skills=match_result["matched_required_skills"],
        matched_preferred_skills=match_result["matched_preferred_skills"],
        missing_required_skills=match_result["missing_required_skills"],
        strengths=ai_result.get("strengths", []),
        weaknesses=ai_result.get("weaknesses", []),
        recommendation=ai_result.get("recommendation", ""),
        reasoning=match_result["reasoning"]
    )
