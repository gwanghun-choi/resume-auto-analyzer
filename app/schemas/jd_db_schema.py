from typing import List, Optional
from pydantic import BaseModel

# /api/jds (DB job_descriptions) 요청 바디입니다.
# required_skills/preferred_skills 는 리스트(JSONB)로 저장합니다.


class JDCreateRequest(BaseModel):
    dept_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    required_skills: List[str] = []
    preferred_skills: List[str] = []
    min_years: Optional[int] = None


class JDUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    required_skills: Optional[List[str]] = None
    preferred_skills: Optional[List[str]] = None
    min_years: Optional[int] = None
    is_active: Optional[bool] = None
