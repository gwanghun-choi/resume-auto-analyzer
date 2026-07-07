from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict

# 관리자 > 사용자 관리 API 요청/응답 스키마입니다.
# 보안 주의: password_hash 는 어떤 응답에도 포함하지 않습니다.


class AdminUserResponse(BaseModel):
    """사용자 목록/상세 응답. (password_hash 미포함)"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    login_id: str
    email: str
    name: str
    role_code: str
    department_id: Optional[str] = None
    department_name: Optional[str] = None
    department_path: Optional[str] = None
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserCreateRequest(BaseModel):
    login_id: str
    email: str
    name: str
    role_code: str
    department_id: Optional[str] = None


class UserUpdateRequest(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None
    role_code: Optional[str] = None
    department_id: Optional[str] = None
    is_active: Optional[bool] = None


class UserCreateResponse(BaseModel):
    """사용자 추가 응답. temporary_password 는 이 응답에서만 1회 노출됩니다."""
    user: AdminUserResponse
    temporary_password: str


class ResetPasswordResponse(BaseModel):
    """비밀번호 초기화 응답. temporary_password 는 이 응답에서만 1회 노출됩니다."""
    user_id: int
    login_id: str
    temporary_password: str


class DepartmentSearchItem(BaseModel):
    id: str
    name: str
    parent_id: Optional[str] = None
    path: str
    is_leaf: bool
