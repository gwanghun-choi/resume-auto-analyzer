"""
기존 더미/테스트 계정의 평문 password_hash 를 bcrypt hash 로 일회성 전환하는 개발용 스크립트입니다.

- 대상은 아래 4개 테스트 계정뿐입니다. (운영 데이터 전체를 추측해서 바꾸지 않습니다.)
- 이미 bcrypt hash 형태($2a$/$2b$/$2y$)면 다시 해시하지 않습니다. (재실행 안전)

실행:
    uv run python scripts/hash_existing_dummy_passwords.py
"""
import os
import sys

# 프로젝트 루트를 import 경로에 추가합니다. (스크립트로 직접 실행 시 'app' 모듈 인식용)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.db.models.user import User
from app.core.password import hash_password, is_bcrypt_hash

# login_id -> 전환할 평문 비밀번호 (개발/더미 계정 전용)
DUMMY_PASSWORDS = {
    "admin": "admin1234",
    "hr.team": "team1234",
    "group": "group1234",
    "ax.team": "team1234",
}


def main():
    session = SessionLocal()
    try:
        updated, skipped, missing = [], [], []
        for login_id, plain in DUMMY_PASSWORDS.items():
            user = session.query(User).filter(User.login_id == login_id).first()
            if not user:
                missing.append(login_id)
                continue
            if is_bcrypt_hash(user.password_hash or ""):
                skipped.append(login_id)  # 이미 bcrypt → 건너뜀
                continue
            user.password_hash = hash_password(plain)
            updated.append(login_id)
        session.commit()
        # 비밀번호 원문은 출력하지 않습니다. (login_id 만 표시)
        print(f"[hash-dummy] updated(bcrypt 전환): {updated}")
        print(f"[hash-dummy] skipped(이미 bcrypt): {skipped}")
        print(f"[hash-dummy] missing(계정 없음): {missing}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
