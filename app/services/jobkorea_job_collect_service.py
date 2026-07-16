import html
import re
from urllib.parse import urljoin

from app.core.config import settings
from app.services.google_drive_service import _log
from app.services.job_extract_service import (
    _assert_safe_url, _fetch_html, JobExtractError,
)
# 회사명 필터는 사람인 수집기와 동일 기준을 재사용합니다(복붙 금지). 잡코리아는 '㈜'(U+321C) 합자
# 표기가 흔해서, 매칭 직전에만 '㈜' → '(주)' 로 치환한 뒤 공용 필터(is_target_company)를 그대로 사용합니다.
from app.services.saramin_job_collect_service import is_target_company

# 잡코리아 검색 결과 페이지를 정적으로 수집해 대상 회사의 신규 공고 후보를 추립니다.
# - 사람인 수집기(saramin_job_collect_service)와 같은 역할/스타일입니다.
#   여기서는 "목록에서 신규 detail_url(공고 고유 GI_No)을 찾는 것" 까지만 담당하고,
#   상세 URL 분석/LLM 구조화는 기존 job_extract_service.extract_from_url(Celery worker)이 수행합니다.
# - HTML fetch 는 job_extract_service._fetch_html(SSRF 방어/크기 제한 포함)을 재사용합니다.
# - 잡코리아 검색 결과는 서버 렌더링(SSR)이라 정적 HTML 로 카드가 존재합니다(2026-07 확인).
#   구조가 바뀌면 아래 파서(정규식)를 수정해야 합니다. (Playwright 미사용 — 정적 수집)
#
# 카드 1건의 실제 DOM(요약):
#   <a href=".../Recruit/GI_Read/49171061?..." ... data-sentry-component="Title"><span>공고 제목</span></a>
#   <span ...><a href=".../Recruit/GI_Read/49171061?..."><span>샘플㈜</span></a></span>
# → 제목 앵커(data-sentry-component="Title")로 gno/제목을 잡고, 같은 gno 의 회사 앵커에서 회사명을 결속합니다.

JOBKOREA_BASE = "https://www.jobkorea.co.kr"

# 제목 앵커: GI_Read/{gno} href + data-sentry-component="Title" + 첫 span 텍스트(제목)
_TITLE_ANCHOR = re.compile(
    r'<a\b[^>]*href="([^"]*GI_Read/(\d+)[^"]*)"[^>]*data-sentry-component="Title"[^>]*>'
    r'\s*<span[^>]*>([^<]*)</span>',
    re.IGNORECASE,
)
# 회사 앵커: 제목 앵커 뒤(같은 카드)에서 같은 gno 의 앵커 첫 span 텍스트(회사명)
_COMPANY_AFTER = (
    r'GI_Read/{gno}[^"]*"[^>]*>\s*<span[^>]*>([^<]+)</span>'
)
_GI_READ = re.compile(r'GI_Read/(\d+)', re.IGNORECASE)
# 회사명 결속을 찾는 전방 탐색 창(카드 하나 범위). 너무 넓으면 다음 카드로 새므로 제한합니다.
_COMPANY_WINDOW = 1500


class JobKoreaCollectError(Exception):
    """검색 결과 수집 자체를 진행할 수 없는 오류. (라우터에서 step/hint JSON 으로 변환)"""
    def __init__(self, message: str, step: str, hint: str = "", status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.step = step
        self.hint = hint
        self.status_code = status_code


def _is_target_company(name: str) -> bool:
    """대상 회사 여부. 잡코리아 '㈜'(U+321C) 합자를 '(주)'로 바꾼 뒤 공용 필터를 재사용합니다."""
    return is_target_company((name or "").replace("㈜", "(주)"))


def extract_gno(url: str) -> str:
    m = _GI_READ.search(url or "")
    return m.group(1) if m else ""


def canonical_detail_url(gno: str) -> str:
    """추적용 query(Oem_Code/logpath/stext/listno/sc 등)를 제거한 표준 상세 URL(중복 판단 기준).

    잡코리아 상세는 GI_No(gno) 하나로 식별되므로, 같은 공고가 tracking parameter 만 다르게 들어와도
    항상 같은 canonical URL 이 됩니다. 상대경로/절대경로와 무관하게 gno 로 재구성합니다.
    """
    return f"{JOBKOREA_BASE}/Recruit/GI_Read/{gno}"


def _parse_cards(raw_html: str) -> list:
    """검색 결과 HTML → 카드 단위 [{company_name, title, detail_url, raw_url, rec_idx, external_id}].
    제목 앵커(data-sentry-component="Title")를 카드 기준점으로 삼고, 같은 gno 의 회사 앵커에서 회사명을
    결속합니다. 회사명을 못 찾은 카드는 건너뜁니다(회사명 없는 등록 금지 — false positive 방지)."""
    items = []
    seen = set()
    for m in _TITLE_ANCHOR.finditer(raw_html):
        raw_href, gno, title = m.group(1), m.group(2), m.group(3)
        if not gno or gno in seen:
            continue
        # 제목 앵커 뒤 창에서 같은 gno 회사 앵커의 첫 span = 회사명
        window = raw_html[m.end():m.end() + _COMPANY_WINDOW]
        cm = re.search(_COMPANY_AFTER.format(gno=re.escape(gno)), window, re.IGNORECASE)
        if not cm:
            continue
        company = html.unescape(cm.group(1).strip())
        if not company:
            continue
        seen.add(gno)
        items.append({
            "company_name": company,
            "title": html.unescape((title or "").strip()),
            "detail_url": canonical_detail_url(gno),
            "raw_url": urljoin(JOBKOREA_BASE, html.unescape(raw_href)),
            "rec_idx": gno,
            "external_id": f"JOBKOREA:{gno}",
        })
    return items


def _scan_gno(raw_html: str) -> set:
    """GI_Read 링크 전체에서 gno 를 스캔합니다(회사명 무관). 파서가 놓친 공고 감지/로깅용."""
    return {m.group(1) for m in _GI_READ.finditer(raw_html)}


def collect_target_postings(search_url: str = None) -> dict:
    """잡코리아 검색 결과를 수집하고 대상 회사 공고만 필터링해 반환합니다.

    반환: {"search_url", "collected_count"(회사명 결속된 카드 수), "items"(대상 회사 매칭만)}.
    fetch/parse 실패 시 JobKoreaCollectError.
    """
    if not settings.target_company_names:
        raise JobKoreaCollectError("수집 대상 회사명이 설정되지 않았습니다.", "target_company_not_configured",
                                   ".env 의 TARGET_COMPANY_NAMES 를 설정해주세요.", status_code=500)
    url = (search_url or settings.JOBKOREA_SEARCH_URL or "").strip()
    if not url:
        raise JobKoreaCollectError("잡코리아 검색 URL 이 설정되지 않았습니다.", "search_url_not_configured",
                                   ".env 의 JOBKOREA_SEARCH_URL 을 확인해주세요.", status_code=500)
    try:
        _assert_safe_url(url)
        raw_html = _fetch_html(url)
    except JobExtractError as e:
        raise JobKoreaCollectError("잡코리아 검색 결과 페이지를 불러오지 못했습니다.", "search_page_fetch_failed",
                                   e.hint, status_code=502) from e

    try:
        cards = _parse_cards(raw_html)
        scan_gnos = _scan_gno(raw_html)
    except Exception as e:
        raise JobKoreaCollectError("잡코리아 검색 결과를 해석하지 못했습니다.", "search_page_parse_failed",
                                   "잡코리아 페이지 구조가 바뀌었을 수 있습니다.", status_code=502) from e

    matched = [it for it in cards if _is_target_company(it["company_name"])]
    parser_missed = len(scan_gnos - {it["rec_idx"] for it in cards})
    _log(f"[jobkorea-collect] cards={len(cards)} link_scan={len(scan_gnos)} "
         f"parser_missed={parser_missed} matched_target={len(matched)}")
    return {"search_url": url, "collected_count": len(cards), "items": matched}
