from pydantic import BaseModel, Field
from typing import List, Optional

# 분석 결과 Schema(DTO) 입니다.
#
# 한 번의 업로드(upload_id)에 여러 이력서 파일이 들어있을 수 있으므로,
# 결과는 "파일별 결과의 리스트" 형태로 돌려줍니다.
#
# 파일 하나가 실패해도 전체를 실패시키지 않습니다.
# 실패한 파일은 error 필드에 사유를 담고, 점수 등은 비어있게 둡니다.


class FileAnalysisResult(BaseModel):
    """이력서 파일 1개에 대한 분석 결과."""
    file_name: str = Field(..., description="분석한 파일명")
    candidate_summary: str = Field("", description="후보자 요약")
    extracted_skills: List[str] = Field(default_factory=list, description="추출된 기술")
    career_summary: str = Field("", description="경력 요약")
    match_score: float = Field(0, description="매칭 점수 (0-100)")
    matched_required_skills: List[str] = Field(default_factory=list, description="매칭된 필수 기술")
    matched_preferred_skills: List[str] = Field(default_factory=list, description="매칭된 우대 기술")
    missing_required_skills: List[str] = Field(default_factory=list, description="부족한 필수 기술")
    strengths: List[str] = Field(default_factory=list, description="강점")
    weaknesses: List[str] = Field(default_factory=list, description="약점")
    recommendation: str = Field("", description="추천 의견 (점수 기준 문구)")
    reasoning: str = Field("", description="판단 근거")
    error: Optional[str] = Field(None, description="이 파일 분석이 실패한 경우의 사유")


class AnalyzeResponse(BaseModel):
    """분석 API 의 최종 응답. 파일별 결과 리스트를 담습니다."""
    dept_id: str = Field(..., description="분석 대상 팀 ID")
    upload_id: str = Field(..., description="분석한 업로드 묶음 ID")
    results: List[FileAnalysisResult] = Field(default_factory=list, description="파일별 분석 결과")
