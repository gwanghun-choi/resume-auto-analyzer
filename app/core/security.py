from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.user import User
from app.services import auth_service

# 인증 관련 공통 유틸/의존성입니다.
# 세션 키: request.session["user_id"] 에 로그인 사용자 PK 를 저장합니다.
SESSION_USER_KEY = "user_id"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    현재 로그인 사용자를 반환하는 FastAPI 의존성입니다.
    - 세션에 user_id 가 없으면 401
    - user_id 는 있으나 사용자가 없거나 비활성이면 401 (세션 무효화)
    다음 단계(JD/이력서 인가)에서 재사용합니다.
    """
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = auth_service.get_active_user_by_id(db, user_id)
    if not user:
        # 세션은 있으나 사용자가 사라졌거나 비활성 → 세션 정리 후 401
        request.session.pop(SESSION_USER_KEY, None)
        raise HTTPException(status_code=401, detail="Invalid session")

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """ADMIN 전용 의존성. 로그인했으나 ADMIN 이 아니면 403. (관리자 사용자/부서검색 API 용)"""
    if (current_user.role_code or "").upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return current_user
