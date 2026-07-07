import secrets

import bcrypt

# 비밀번호 해시/검증 + 임시 비밀번호 생성 유틸입니다.
# 보안 주의:
#   - 비밀번호 원문은 DB 에 저장하지 않습니다. (bcrypt hash 만 저장)
#   - 비밀번호 원문/해시는 로그에 출력하지 않습니다.

# bcrypt hash 의 prefix (이미 해시된 값인지 판단용)
_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")

# 임시 비밀번호 생성용 문자집합 (헷갈리는 문자 0/O/1/l/I 제외)
_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_LOWER = "abcdefghijkmnopqrstuvwxyz"
_DIGITS = "23456789"
_SYMBOLS = "!@#$%^&*?"


def hash_password(raw_password: str) -> str:
    """평문 비밀번호를 bcrypt hash 문자열로 변환합니다."""
    # bcrypt 는 72바이트까지만 사용하지만 임시 비밀번호는 짧아 문제 없습니다.
    return bcrypt.hashpw(raw_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw_password: str, password_hash: str) -> bool:
    """평문 비밀번호가 저장된 bcrypt hash 와 일치하는지 검증합니다. (형식 오류 시 False)"""
    if not raw_password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(raw_password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # 평문이 들어있는 등 bcrypt 형식이 아닌 경우 검증 실패로 처리
        return False


def is_bcrypt_hash(value: str) -> bool:
    """주어진 문자열이 이미 bcrypt hash 형태인지 prefix 로 판단합니다."""
    return bool(value) and value.startswith(_BCRYPT_PREFIXES)


def generate_temporary_password(length: int = 12) -> str:
    """
    임시 비밀번호를 생성합니다. (대문자/소문자/숫자/특수문자 각 1개 이상 보장)
    length 는 최소 10 으로 보정합니다.
    """
    length = max(10, length)
    pools = [_UPPER, _LOWER, _DIGITS, _SYMBOLS]
    # 각 그룹에서 최소 1개씩
    chars = [secrets.choice(pool) for pool in pools]
    all_chars = _UPPER + _LOWER + _DIGITS + _SYMBOLS
    chars += [secrets.choice(all_chars) for _ in range(length - len(chars))]
    # 위치 셔플 (secrets 기반)
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)
