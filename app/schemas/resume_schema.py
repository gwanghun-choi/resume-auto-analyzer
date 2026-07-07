from pydantic import BaseModel, Field
from typing import List, Optional

# Pydantic schema는 Java/Spring Boot의 DTO(Data Transfer Object)와 비슷합니다.
# 데이터를 주고받을 때 구조를 정의하고 자동 검증을 수행합니다.

class ResumeAnalysisRequest(BaseModel):
    position: str = Field(..., description="지원 포지션명")
    required_skills: List[str] = Field(..., description="필수 기술 스택 리스트")
    preferred_skills: List[str] = Field(..., description="우대 기술 스택 리스트")

class ResumeAnalysisResponse(BaseModel):
    candidate_summary: str = Field(..., description="후보자 요약")
    extracted_skills: List[str] = Field(..., description="추출된 기술 스택")
    career_summary: str = Field(..., description="경력 요약")
    match_score: float = Field(..., description="최종 매칭 점수 (0-100)")
    matched_required_skills: List[str] = Field(..., description="매칭된 필수 기술")
    matched_preferred_skills: List[str] = Field(..., description="매칭된 우대 기술")
    missing_required_skills: List[str] = Field(..., description="누락된 필수 기술")
    strengths: List[str] = Field(..., description="강점")
    weaknesses: List[str] = Field(..., description="약점/보완점")
    recommendation: str = Field(..., description="채용 추천 여부 및 의견")
    reasoning: str = Field(..., description="점수 산출 근거")
