from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.user import User
from app.core.security import require_admin
from app.services import admin_user_service, department_access_service
from app.schemas.admin_user_schema import (
    AdminUserResponse,
    UserCreateRequest,
    UserUpdateRequest,
    UserCreateResponse,
    ResetPasswordResponse,
    DepartmentSearchItem,
)

# 관리자 > 사용자 관리 라우터. 모든 엔드포인트는 ADMIN 만 접근 가능(require_admin → 비ADMIN 403).
# 보안 주의: password_hash 는 어떤 응답에도 포함하지 않습니다.

router = APIRouter(prefix="/api/admin", tags=["Admin-Users"])


@router.get("/users", response_model=List[AdminUserResponse])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    """사용자 목록(부서 name/path 포함)을 반환합니다."""
    return admin_user_service.list_users(db)


@router.get("/users/{user_id}", response_model=AdminUserResponse)
def get_user(user_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """사용자 1명 상세를 반환합니다."""
    user = admin_user_service.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    return user


@router.post("/users", response_model=UserCreateResponse)
def create_user(body: UserCreateRequest, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """사용자를 추가하고 임시 비밀번호를 1회 반환합니다. (DB 에는 bcrypt hash 만 저장)"""
    user, temp_password = admin_user_service.create_user(db, body)
    return {"user": user, "temporary_password": temp_password}


@router.put("/users/{user_id}", response_model=AdminUserResponse)
def update_user(user_id: int, body: UserUpdateRequest,
                current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """사용자 정보를 수정합니다. (login_id/password_hash 변경 불가, 마지막 ADMIN/본인 보호)"""
    return admin_user_service.update_user(db, user_id, body, current_user)


@router.patch("/users/{user_id}/activate", response_model=AdminUserResponse)
def activate_user(user_id: int, current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """사용자를 활성화합니다."""
    return admin_user_service.set_active(db, user_id, True, current_user)


@router.patch("/users/{user_id}/deactivate", response_model=AdminUserResponse)
def deactivate_user(user_id: int, current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """사용자를 비활성화합니다. (본인/마지막 활성 ADMIN 은 차단)"""
    return admin_user_service.set_active(db, user_id, False, current_user)


@router.patch("/users/{user_id}/reset-password", response_model=ResetPasswordResponse)
def reset_password(user_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """비밀번호를 임시 비밀번호로 초기화하고 1회 반환합니다."""
    login_id, temp_password = admin_user_service.reset_password(db, user_id)
    return {"user_id": user_id, "login_id": login_id, "temporary_password": temp_password}


@router.get("/departments/search", response_model=List[DepartmentSearchItem])
def search_departments(keyword: str = "", _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """부서/팀을 id 또는 name 부분일치로 검색합니다. (사용자 추가/수정의 부서 선택용)"""
    return department_access_service.search_departments(db, keyword)
