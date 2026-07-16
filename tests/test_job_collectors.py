"""JobKorea 수집기 / platform_code 매핑 / URL 정규화 / 중복·dry-run 단위 테스트.

pytest 의존성 없이 `uv run python tests/test_job_collectors.py` 로 실행합니다(프로젝트에 pytest 미도입).
네트워크/DB 없이 순수 함수만 검증합니다(파서는 아래 고정 fixture HTML 사용).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services import jobkorea_job_collect_service as jk
from app.services import job_posting_discovery_service as disc
from app.services import job_extract_service as je

# 회사명 필터는 .env(TARGET_COMPANY_NAMES) 로 주입되므로, 테스트는 가상 회사명을 명시적으로 설정합니다.
# (실제 배포 값에 의존하지 않도록 테스트 안에서 고정)
settings.TARGET_COMPANY_NAMES = "샘플(주),샘플주식회사"

# 잡코리아 검색 결과 SSR DOM 을 축약한 fixture. 샘플㈜ 2건 + 상호가 비슷한 제외 회사 1건.
FIXTURE = """
<div class="mb-0.5">
  <a href="https://www.jobkorea.co.kr/Recruit/GI_Read/49171061?Oem_Code=C1&amp;logpath=1&amp;stext=x&amp;listno=1&amp;sc=630"
     rel="noopener" target="_blank" class="mb-0.5 flex" data-interactive="true"
     data-sentry-element="BaseLink" data-sentry-component="Title" data-sentry-source-file="index.tsx">
     <span class="truncate font-semibold">인프라 운영 엔지니어 채용</span></a></div>
<span class="mb-5 inline-flex">
  <a href="https://www.jobkorea.co.kr/Recruit/GI_Read/49171061?Oem_Code=C1&amp;listno=1"
     rel="noopener" target="_blank" data-sentry-element="BaseLink" data-sentry-source-file="index.tsx">
     <span class="truncate text-gray700">샘플㈜</span><span class="text-gray500"></span></a></span>

<div class="mb-0.5">
  <a href="/Recruit/GI_Read/49406903?logpath=1&amp;listno=2"
     class="mb-0.5 flex" data-sentry-component="Title" data-sentry-source-file="index.tsx">
     <span class="truncate">백엔드 엔지니어 채용</span></a></div>
<span class="mb-5">
  <a href="/Recruit/GI_Read/49406903?listno=2"><span class="text-gray700">샘플(주)</span></a></span>

<div class="mb-0.5">
  <a href="https://www.jobkorea.co.kr/Recruit/GI_Read/49332947?listno=3"
     data-sentry-component="Title" data-sentry-source-file="index.tsx">
     <span>마케팅 담당자 모집</span></a></div>
<span><a href="https://www.jobkorea.co.kr/Recruit/GI_Read/49332947?listno=3">
  <span class="text-gray700">㈜샘플커뮤니케이션</span></a></span>
"""

_fails = []


def check(name, cond):
    print(("  ok  " if cond else " FAIL ") + name)
    if not cond:
        _fails.append(name)


def test_platform_mapping():
    print("[platform_code_for_url]")
    check("saramin -> SARAMIN",
          je.platform_code_for_url("https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=1") == "SARAMIN")
    check("jobkorea -> JOBKOREA",
          je.platform_code_for_url("https://www.jobkorea.co.kr/Recruit/GI_Read/49171061") == "JOBKOREA")
    check("sub-domain jobkorea -> JOBKOREA",
          je.platform_code_for_url("https://m.jobkorea.co.kr/Recruit/GI_Read/1") == "JOBKOREA")
    check("wanted -> WANTED", je.platform_code_for_url("https://www.wanted.co.kr/wd/1") == "WANTED")
    check("unknown -> None", je.platform_code_for_url("https://example.com/x") is None)
    check("empty -> None", je.platform_code_for_url("") is None)


def test_url_normalize():
    print("[canonical_detail_url / extract_gno]")
    raw = "/Recruit/GI_Read/49171061?Oem_Code=C1&logpath=1&stext=%EB%94%94%EB%94%A4&listno=1&sc=630"
    check("extract_gno from tracking url", jk.extract_gno(raw) == "49171061")
    check("canonical strips tracking",
          jk.canonical_detail_url("49171061") == "https://www.jobkorea.co.kr/Recruit/GI_Read/49171061")
    # tracking parameter 만 다른 두 URL 이 같은 canonical 로 정규화
    a = jk.canonical_detail_url(jk.extract_gno(raw))
    b = jk.canonical_detail_url(jk.extract_gno("https://www.jobkorea.co.kr/Recruit/GI_Read/49171061?x=9&y=8"))
    check("same posting different tracking -> same canonical", a == b)


def test_company_filter():
    print("[_is_target_company]")
    for ok in ["샘플㈜", "샘플(주)", "샘플 (주)", "샘플 주식회사"]:
        check(f"allow {ok}", jk._is_target_company(ok) is True)
    # 상호 앞뒤에 다른 토큰이 붙은 회사는 exact 매칭에서 제외되어야 합니다(false positive 방지).
    for no in ["㈜샘플커뮤니케이션", "샘플정신건강의학과의원", "샘플터", "샘플돌미술학원", ""]:
        check(f"exclude {no or '(empty)'}", jk._is_target_company(no) is False)


def test_parser_fixture():
    print("[_parse_cards fixture]")
    cards = jk._parse_cards(FIXTURE)
    check("parsed 3 cards", len(cards) == 3)
    matched = [c for c in cards if jk._is_target_company(c["company_name"])]
    check("matched 2 샘플(주)", len(matched) == 2)
    gnos = sorted(c["rec_idx"] for c in matched)
    check("matched gnos", gnos == ["49171061", "49406903"])
    c0 = next(c for c in cards if c["rec_idx"] == "49171061")
    check("title parsed", c0["title"] == "인프라 운영 엔지니어 채용")
    check("canonical detail_url", c0["detail_url"] == "https://www.jobkorea.co.kr/Recruit/GI_Read/49171061")
    check("raw_url absolute", c0["raw_url"].startswith("https://www.jobkorea.co.kr/Recruit/GI_Read/49171061?"))
    check("external_id", c0["external_id"] == "JOBKOREA:49171061")
    # 상대경로 href 도 절대 URL 로 변환
    c1 = next(c for c in cards if c["rec_idx"] == "49406903")
    check("relative href -> absolute raw_url", c1["raw_url"].startswith("https://www.jobkorea.co.kr/Recruit/GI_Read/49406903"))


def test_dry_run_shape():
    print("[_dry_run_items shape + duplicate]")
    items = [
        {"company_name": "샘플㈜", "title": "A", "detail_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/1",
         "raw_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/1?x=1", "rec_idx": "1"},
        {"company_name": "샘플㈜", "title": "B", "detail_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/2",
         "raw_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/2?x=2", "rec_idx": "2"},
    ]
    # _find_existing 를 스텁: gno=1 은 기존(중복), gno=2 는 신규
    orig = disc._find_existing
    disc._find_existing = lambda db, pc, url, rec: (99 if rec == "1" else None)
    try:
        out = disc._dry_run_items(db=None, platform_code="JOBKOREA", items=items)
    finally:
        disc._find_existing = orig
    keys = {"platform_code", "company_name", "title", "raw_url", "normalized_url",
            "rec_idx", "is_duplicate", "skip_reason"}
    check("all required keys", all(keys <= set(r) for r in out))
    check("dup flagged for gno=1", out[0]["is_duplicate"] is True and out[0]["skip_reason"] == "duplicate_job_posting")
    check("new for gno=2", out[1]["is_duplicate"] is False and out[1]["skip_reason"] is None)
    check("platform_code stamped", all(r["platform_code"] == "JOBKOREA" for r in out))


if __name__ == "__main__":
    for t in (test_platform_mapping, test_url_normalize, test_company_filter,
              test_parser_fixture, test_dry_run_shape):
        t()
    print()
    if _fails:
        print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
        sys.exit(1)
    print("ALL PASSED")
