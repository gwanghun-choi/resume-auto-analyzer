"""DB 세션 주입(H6) 회귀 테스트.

pytest 의존성 없이 `uv run python tests/test_db_session_injection.py` 로 실행합니다(프로젝트에 pytest 미도입).
실제 DB 없이 검증합니다:
  - resolve_session 의미론: 세션을 주면 재사용(own=False), 안 주면 새로 열고(own=True) 호출부가 닫음.
  - db_service 공개 함수는 주입된 세션을 '사용'하되 '닫지 않는다'(세션 생명주기는 주입한 쪽 소유).
  - 6개 *_db_service 모듈의 모든 공개 함수가 session 키워드(기본 None)를 받는다(계약).
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import resolve_session
from app.services import department_db_service
from app.services import jd_db_service
from app.services import dept_drive_folder_db_service
from app.services import resume_upload_db_service
from app.services import resume_status_db_service
from app.services import resume_analysis_db_service

_fails = []


def check(name, cond):
    print(("  ok  " if cond else " FAIL ") + name)
    if not cond:
        _fails.append(name)


class _FakeSession:
    """query() 호출/close() 호출을 기록하는 스텁 세션. (DB 접속 없음)

    raise_on_query=True 이면 query 진입 즉시 예외를 던져, 실패 경로에서도
    '주입 세션은 닫히지 않는다'는 성질을 검증할 수 있게 합니다.
    """

    def __init__(self, raise_on_query=True):
        self.closed = False
        self.queried = False
        self.rolled_back = False
        self.raise_on_query = raise_on_query

    def query(self, *a, **k):
        self.queried = True
        if self.raise_on_query:
            raise RuntimeError("stub-query")
        return self

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_resolve_session_semantics():
    print("[resolve_session]")
    fake = _FakeSession()
    s, own = resolve_session(fake)
    check("주입 세션은 그대로 재사용", s is fake)
    check("주입 세션은 own=False (호출부가 닫지 않음)", own is False)

    s2, own2 = resolve_session(None)
    check("미주입 시 새 세션 반환", s2 is not None and s2 is not fake)
    check("미주입 시 own=True (호출부가 닫음)", own2 is True)
    s2.close()  # own=True 인 세션은 호출부가 정리


def test_injected_session_not_closed():
    print("[주입 세션 close 안 함 — 읽기/쓰기 경로]")
    # 읽기 함수(count): 주입 세션을 사용하고, 예외가 나도 닫지 않아야 함
    fake = _FakeSession(raise_on_query=True)
    try:
        department_db_service.count(session=fake)
    except RuntimeError:
        pass
    check("읽기: 주입 세션을 사용함(query 호출)", fake.queried is True)
    check("읽기: 주입 세션을 닫지 않음", fake.closed is False)

    # 쓰기 함수(set_processing): 실패 시 rollback 은 하되 주입 세션은 닫지 않아야 함
    fake_w = _FakeSession(raise_on_query=True)
    try:
        resume_analysis_db_service.set_processing(1, session=fake_w)
    except RuntimeError:
        pass
    check("쓰기: 실패 시 rollback 호출", fake_w.rolled_back is True)
    check("쓰기: 주입 세션을 닫지 않음", fake_w.closed is False)


def test_session_param_contract():
    print("[시그니처 계약 — 모든 공개 함수가 session=None 을 받음]")
    modules = [
        department_db_service, jd_db_service, dept_drive_folder_db_service,
        resume_upload_db_service, resume_status_db_service, resume_analysis_db_service,
    ]
    ok = True
    checked = 0
    for mod in modules:
        for name, fn in inspect.getmembers(mod, inspect.isfunction):
            if name.startswith("_"):
                continue
            if fn.__module__ != mod.__name__:  # import 된 함수(resolve_session 등)는 제외
                continue
            params = inspect.signature(fn).parameters
            has = "session" in params and params["session"].default is None
            checked += 1
            if not has:
                ok = False
                print(f"      -> 누락: {mod.__name__}.{name}")
    check(f"공개 db_service 함수 {checked}개 모두 session=None 수용", ok and checked > 0)


if __name__ == "__main__":
    for t in (test_resolve_session_semantics,
              test_injected_session_not_closed,
              test_session_param_contract):
        t()
    print()
    if _fails:
        print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
        sys.exit(1)
    print("ALL PASSED")
