"""
로컬 시드 계정의 평문 password_hash 를 bcrypt hash 로 일회성 전환하는 개발용 스크립트입니다.

- 대상 계정/비밀번호는 코드에 두지 않고 환경변수 DUMMY_ACCOUNT_PASSWORDS 로만 주입합니다.
  (비밀번호를 저장소에 커밋하지 않기 위함. 미설정 시 아무것도 하지 않고 종료합니다.)
- 이미 bcrypt hash 형태($2a$/$2b$/$2y$)면 다시 해시하지 않습니다. (재실행 안전)
- 개발 환경 전용입니다. 운영 DB 를 가리키는 .env 로 실행하지 마세요.

실행:
    DUMMY_ACCOUNT_PASSWORDS="admin:localpw1,hr.team:localpw2" \\
        uv run python scripts/hash_existing_dummy_passwords.py
"""
import os
import sys

# 프로젝트 루트를 import 경로에 추가합니다. (스크립트로 직접 실행 시 'app' 모듈 인식용)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.db.models.user import User
from app.core.password import hash_password, is_bcrypt_hash

# login_id -> 전환할 평문 비밀번호. 환경변수에서만 읽습니다(코드/저장소에 비밀번호 하드코딩 금지).
# 형식: "login_id:password,login_id:password"
def _load_dummy_passwords() -> dict:
    raw = os.getenv("DUMMY_ACCOUNT_PASSWORDS", "").strip()
    if not raw:
        return {}
    pairs = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise SystemExit(f"[hash-dummy] 형식 오류: '{entry}' — login_id:password 형식이어야 합니다.")
        login_id, _, plain = entry.partition(":")
        if not login_id.strip() or not plain:
            raise SystemExit("[hash-dummy] login_id 와 password 는 비어 있을 수 없습니다.")
        pairs[login_id.strip()] = plain
    return pairs


def main():
    dummy_passwords = _load_dummy_passwords()
    if not dummy_passwords:
        print("[hash-dummy] DUMMY_ACCOUNT_PASSWORDS 가 설정되지 않아 아무 작업도 하지 않습니다.")
        print('[hash-dummy] 예: DUMMY_ACCOUNT_PASSWORDS="admin:localpw1,hr.team:localpw2"')
        return
    session = SessionLocal()
    try:
        updated, skipped, missing = [], [], []
        for login_id, plain in dummy_passwords.items():
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
