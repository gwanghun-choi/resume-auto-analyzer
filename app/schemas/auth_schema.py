from typing import List, Optional
from pydantic import BaseModel, ConfigDict

# /api/auth 요청/응답 스키마입니다.


class LoginRequest(BaseModel):
    login_id: str
    password: str


class VerifyPasswordRequest(BaseModel):
    password: str


class ProfileUpdateRequest(BaseModel):
    """내 정보 수정 요청. email 은 필수, new_password 비어 있으면 비밀번호 변경 안 함."""
    email: str
    new_password: str = ""
    new_password_confirm: str = ""


class UserResponse(BaseModel):
    """로그인 사용자 기본 정보. (password_hash 등 민감정보는 노출하지 않습니다)"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    login_id: str
    email: str
    name: str
    role_code: str
    # departments.id(문자열) 를 참조하는 소속 부서 ID. (ADMIN 은 보통 null)
    department_id: Optional[str] = None


class DepartmentAccessItem(BaseModel):
    """접근 가능한 부서 1건. is_leaf(최하위 팀) 여부로 JD 등록/이력서 업로드 가능 여부를 계산합니다."""
    id: str
    name: str
    parent_id: Optional[str] = None
    manager_id: Optional[str] = None
    email: Optional[str] = None
    is_leaf: bool
    can_register_jd: bool
    can_upload_resume: bool


class MeDepartmentsResponse(BaseModel):
    """현재 로그인 사용자 + 접근 가능한 부서 목록."""
    user: UserResponse
    departments: List[DepartmentAccessItem]
