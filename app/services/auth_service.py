import re
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models.user import User
from app.core import password as password_util

# 기본 이메일 형식 검증용 (백엔드 1차 검증; 복잡한 RFC 검증은 하지 않음)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# auth_service 는 resume_ai.users 테이블만 다룹니다. (로그인/세션용 조회·검증)
# 보안 주의:
#   - 비밀번호/해시 값을 로그로 출력하지 않습니다.
#   - 세션에는 user_id 만 저장하고 password_hash 는 저장하지 않습니다.


def get_user_by_login_id(db: Session, login_id: str) -> User | None:
    """login_id 로 사용자 1명을 조회합니다. 없으면 None."""
    return db.query(User).filter(User.login_id == login_id).first()


def get_active_user_by_id(db: Session, user_id: int) -> User | None:
    """활성(is_active=true) 사용자 1명을 id 로 조회합니다. 없거나 비활성이면 None."""
    return (
        db.query(User)
        .filter(User.id == user_id, User.is_active.is_(True))
        .first()
    )


def verify_password(plain_password: str, password_hash: str) -> bool:
    """비밀번호를 bcrypt hash 기준으로 검증합니다. (평문 저장은 더 이상 지원하지 않음)"""
    return password_util.verify_password(plain_password, password_hash)


def touch_last_login(db: Session, user: User) -> None:
    """로그인 성공 시 last_login_at 을 현재 시각으로 갱신합니다."""
    user.last_login_at = datetime.now()
    db.commit()


def update_own_profile(db: Session, user: User, email: str,
                       new_password: str, new_password_confirm: str) -> User:
    """
    본인(current_user) 의 이메일/비밀번호만 수정합니다.
    (role_code/department_id/login_id/name/is_active 등은 절대 변경하지 않습니다.)
    - 이메일: 형식 검증 + 본인 제외 중복 검증
    - 비밀번호: new_password 가 비어 있으면 변경 안 함, 입력 시 confirm 일치 검증 후 bcrypt 저장
    TODO: 추후 비밀번호 길이, 복잡도, 만료 정책을 추가할 예정입니다.
    TODO: 보안 정책 강화 시 프로필 저장 시점에도 현재 비밀번호를 재검증할 수 있습니다.
    """
    email = (email or "").strip()
    if not email or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="올바른 이메일 형식이 아닙니다.")
    # 본인 제외 이메일 중복 체크
    dup = db.query(User).filter(User.email == email, User.id != user.id).first()
    if dup:
        raise HTTPException(status_code=400, detail="이미 사용 중인 이메일입니다.")

    if new_password:
        if new_password != new_password_confirm:
            raise HTTPException(status_code=400, detail="새 비밀번호와 확인 값이 일치하지 않습니다.")
        # 비밀번호 원문은 로그/DB 에 남기지 않고 bcrypt hash 로만 저장합니다.
        user.password_hash = password_util.hash_password(new_password)

    user.email = email
    user.updated_at = datetime.now()
    try:
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise
    return user
