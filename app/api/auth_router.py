from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.user import User
from app.schemas.auth_schema import (
    LoginRequest, UserResponse, MeDepartmentsResponse,
    VerifyPasswordRequest, ProfileUpdateRequest,
)
from app.services import auth_service, department_access_service
from app.core.security import get_current_user, SESSION_USER_KEY

# 로그인/로그아웃/me 인증 라우터입니다. (세션 기반)
# 이번 단계 목표: "로그인한 사용자만 시스템에 접근 가능". 부서별 인가는 다음 단계에서 구현합니다.

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/login", response_model=UserResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """
    login_id/password 로 로그인합니다. 성공 시 세션에 user_id 를 저장합니다.
    - 사용자 없음 → 401
    - 비활성 사용자 → 403
    - 비밀번호 불일치 → 401 (입력 비밀번호는 로그/응답에 노출하지 않음)
    """
    user = auth_service.get_user_by_login_id(db, body.login_id)
    if not user:
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다.")
    if not auth_service.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")

    # 세션에는 user_id 만 저장 (password_hash 등 민감정보 저장 금지)
    request.session[SESSION_USER_KEY] = user.id
    auth_service.touch_last_login(db, user)
    return UserResponse.model_validate(user)


@router.post("/logout")
def logout(request: Request):
    """세션에서 user_id 를 제거합니다. (이미 로그아웃 상태여도 200)"""
    request.session.pop(SESSION_USER_KEY, None)
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    """현재 로그인 사용자 정보를 반환합니다. 미로그인/세션무효 시 401."""
    return UserResponse.model_validate(current_user)


@router.post("/verify-password")
def verify_password(body: VerifyPasswordRequest, current_user: User = Depends(get_current_user)):
    """
    현재 로그인 사용자의 비밀번호를 확인합니다. (내 정보 수정 진입 전 본인 확인)
    불일치 시 401. (입력 비밀번호는 로그/응답에 노출하지 않음)
    """
    if not auth_service.verify_password(body.password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="비밀번호가 일치하지 않습니다.")
    return {"ok": True}


@router.put("/me/profile", response_model=UserResponse)
def update_my_profile(
    body: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    본인의 이메일/비밀번호만 수정합니다. (role_code/department_id/login_id/name/is_active 변경 불가)
    다른 사용자 id 지정 불가 — 항상 current_user 기준으로만 수정합니다.
    """
    user = auth_service.update_own_profile(
        db, current_user, body.email, body.new_password, body.new_password_confirm
    )
    return UserResponse.model_validate(user)


@router.get("/me/departments", response_model=MeDepartmentsResponse)
def me_departments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    현재 로그인 사용자가 접근 가능한 부서 목록을 반환합니다. (미로그인 401)
    - ADMIN: 전체 부서
    - MANAGER/VIEWER: department_id 기준 해당 부서 + 하위 부서 전체
    다음 단계의 부서 트리 제한 / JD·이력서 인가에서 재사용합니다.
    """
    departments = department_access_service.get_accessible_departments(db, current_user)
    return {"user": current_user, "departments": departments}
