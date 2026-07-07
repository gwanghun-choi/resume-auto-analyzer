from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

# 공고/JD 관리 요청·응답 스키마입니다. (response 는 service 가 dict 로 구성 → 모양 검증용)


class PostingCreateRequest(BaseModel):
    title: str
    department_id: Optional[str] = None   # 부서/팀은 선택사항(미지정 가능)
    platform_code: Optional[str] = None
    platform_posting_url: Optional[str] = None
    status: str = "OPEN"


class JobExtractRequest(BaseModel):
    """공고 URL 자동 추출 요청. (화면 입력값 자동 채우기용 — 저장 안 함)"""
    url: str


class PostingUpdateRequest(BaseModel):
    title: Optional[str] = None
    department_id: Optional[str] = None
    platform_code: Optional[str] = None
    platform_posting_url: Optional[str] = None
    status: Optional[str] = None


class PostingStatusRequest(BaseModel):
    status: str


class JDUpsertRequest(BaseModel):
    """공고 JD 등록/수정. 현재 공고당 1 active JD (백엔드 강제)."""
    title: Optional[str] = None
    required_skills: List[str] = []
    preferred_skills: List[str] = []
    jd_content: Optional[str] = None


class JDResponse(BaseModel):
    id: int
    posting_id: int
    title: Optional[str] = None
    required_skills: List[str] = []
    preferred_skills: List[str] = []
    jd_content: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PostingResponse(BaseModel):
    id: int
    title: str
    department_id: str
    department_name: Optional[str] = None
    department_path: Optional[str] = None
    platform_code: Optional[str] = None
    platform_label: Optional[str] = None
    platform_posting_url: Optional[str] = None
    status: str
    has_jd: bool = False
    jd_status: str = "JD 미등록"   # 'JD 미등록' / 'JD 등록 완료'
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
