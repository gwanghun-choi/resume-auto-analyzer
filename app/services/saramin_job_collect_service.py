import html
import re
from urllib.parse import urljoin

from app.core.config import settings
from app.services.google_drive_service import _log
from app.services.job_extract_service import (
    _assert_safe_url, _fetch_html, JobExtractError,
)

# 사람인 '디딤' 검색 결과 페이지를 정적으로 수집해 디딤(주) 신규 공고 후보를 추립니다.
# - 상세 URL 분석/LLM 구조화는 이 서비스가 하지 않습니다(기존 job_extract_service.extract_from_url 재사용).
#   여기서는 "목록에서 신규 detail_url 을 찾는 것" 까지만 담당합니다.
# - HTML fetch 는 job_extract_service._fetch_html(SSRF 방어/크기 제한 포함)을 재사용합니다.
# - 사람인 HTML 구조가 바뀌면 아래 파서(정규식)를 수정해야 합니다. (Playwright 미사용 — 정적 수집)
#
# 파싱은 3단계로 견고화했습니다(모두 정적 정규식):
#   1차 _parse_items         : 기존 div.item_recruit 카드 + corp_name + job_tit/view href.
#   2차 _parse_items_fallback: corp_name 을 기준으로 세그먼트를 나눠, 그 안의 a.str_tit / a[id^=rec_link_] /
#                              relay/view href 앵커에서 rec_idx 를 뽑고 회사명을 결속(카드 컨테이너 클래스가 바뀌어도 동작).
#   3차 _scan_view_rec_idx   : relay/view href 또는 rec_link id 를 가진 a 태그 전체 스캔(회사명 무관, 감지/로깅용).
#                              회사명을 결속하지 못한 링크는 등록하지 않습니다(section: false positive 금지).
# 결과는 rec_idx 기준으로 dedupe 하며 1차(회사명/제목이 더 정확) 결과를 우선합니다.

SARAMIN_BASE = "https://www.saramin.co.kr"

# 디딤(주) 로 인정할 회사명(정규화=모든 공백 제거 후 비교). 검색어가 '디딤'이라고 모두 같은 회사가 아니므로
# exact(normalize 후) 매칭만 통과시킵니다. (예: '디딤 정신건강의학과의원', '(주)디딤 커뮤니케이션' 등은 제외)
#   허용:  디딤(주) / 디딤 (주) / 디딤 주식회사
ALLOWED_COMPANY_NORMALIZED = {"디딤(주)", "디딤주식회사"}

# 검색 결과 카드(div.item_recruit) 단위 파싱용 정규식 (1차)
_ITEM_SPLIT = re.compile(r'<div[^>]*class="[^"]*\bitem_recruit\b[^"]*"', re.IGNORECASE)
_CORP_NAME = re.compile(
    r'class="[^"]*\bcorp_name\b[^"]*"[^>]*>\s*(?:<a[^>]*>)?\s*([^<]+)', re.IGNORECASE)
_VIEW_LINK = re.compile(
    r'href="([^"]*/zf_user/jobs/relay/view[^"]*rec_idx=\d+[^"]*)"', re.IGNORECASE)
_JOB_TIT = re.compile(
    r'class="[^"]*\bjob_tit\b[^"]*"[^>]*>\s*<a[^>]*\btitle="([^"]*)"', re.IGNORECASE)
_REC_IDX = re.compile(r'rec_idx=(\d+)')

# fallback(2·3차)용 정규식
_CORP_NAME_MARK = re.compile(r'class="[^"]*\bcorp_name\b[^"]*"', re.IGNORECASE)  # corp_name 세그먼트 경계
_ANCHOR_FULL = re.compile(r'<a\b[^>]*>.*?</a>', re.IGNORECASE | re.DOTALL)       # <a ...>...</a> 전체
_A_OPEN = re.compile(r'<a\b[^>]*>', re.IGNORECASE)                              # 여는 a 태그만
_HREF = re.compile(r'href="([^"]*)"', re.IGNORECASE)
_ID_REC_LINK = re.compile(r'id="rec_link_(\d+)"', re.IGNORECASE)                # id="rec_link_숫자"
_TITLE_ATTR = re.compile(r'\btitle="([^"]*)"', re.IGNORECASE)
_SPAN_TEXT = re.compile(r'<span[^>]*>(.*?)</span>', re.IGNORECASE | re.DOTALL)
_ANY_TAG = re.compile(r'<[^>]+>')


class SaraminCollectError(Exception):
    """검색 결과 수집 자체를 진행할 수 없는 오류. (라우터에서 step/hint JSON 으로 변환)"""
    def __init__(self, message: str, step: str, hint: str = "", status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.step = step
        self.hint = hint
        self.status_code = status_code


def normalize_company(name: str) -> str:
    """회사명 비교용 정규화: HTML unescape + 모든 공백 제거. '디딤 (주)' → '디딤(주)'."""
    s = html.unescape(name or "").strip()
    return re.sub(r"\s+", "", s)


def is_didim_company(name: str) -> bool:
    """정규화 후 디딤(주) 계열(허용 목록)과 정확히 일치할 때만 True."""
    return normalize_company(name) in ALLOWED_COMPANY_NORMALIZED


def extract_rec_idx(url: str) -> str:
    m = _REC_IDX.search(url or "")
    return m.group(1) if m else ""


def canonical_detail_url(rec_idx: str) -> str:
    """추적용 query 를 제거한 표준 상세 URL(중복 판단 기준). rec_idx 기반 절대경로."""
    return f"{SARAMIN_BASE}/zf_user/jobs/relay/view?rec_idx={rec_idx}"


def _parse_items(raw_html: str) -> list:
    """검색 결과 HTML → 카드 단위 [{company_name, title, detail_url, rec_idx, external_id}].
    회사명/링크가 없는 카드는 건너뜁니다. (필터는 하지 않고 파싱 전체를 반환)"""
    chunks = _ITEM_SPLIT.split(raw_html)
    items = []
    seen_rec = set()
    for chunk in chunks[1:]:   # chunks[0]=첫 카드 이전 헤더 → 제외
        link_m = _VIEW_LINK.search(chunk)
        corp_m = _CORP_NAME.search(chunk)
        if not link_m or not corp_m:
            continue
        rec_idx = extract_rec_idx(link_m.group(1))
        if not rec_idx or rec_idx in seen_rec:
            continue
        seen_rec.add(rec_idx)
        tit_m = _JOB_TIT.search(chunk)
        title = html.unescape((tit_m.group(1) if tit_m else "").strip())
        items.append({
            "company_name": html.unescape(corp_m.group(1).strip()),
            "title": title,
            "detail_url": canonical_detail_url(rec_idx),
            "rec_idx": rec_idx,
            "external_id": f"SARAMIN:{rec_idx}",
        })
    return items


def _rec_idx_from_anchor(open_tag: str) -> str:
    """여는 a 태그에서 rec_idx 추출: 1) href query string 2) id="rec_link_숫자". 없으면 ''."""
    href_m = _HREF.search(open_tag)
    if href_m:
        rid = extract_rec_idx(href_m.group(1))
        if rid:
            return rid
    id_m = _ID_REC_LINK.search(open_tag)
    return id_m.group(1) if id_m else ""


def _title_from_anchor(open_tag: str, inner_html: str) -> str:
    """제목 우선순위: 1) a title 속성 2) 내부 span text 3) a 내부 text 4) ''(호출측에서 '(제목 미상)' 처리)."""
    m = _TITLE_ATTR.search(open_tag)
    if m and m.group(1).strip():
        return html.unescape(m.group(1).strip())
    sp = _SPAN_TEXT.search(inner_html or "")
    if sp:
        t = html.unescape(_ANY_TAG.sub("", sp.group(1)).strip())
        if t:
            return t
    return html.unescape(_ANY_TAG.sub("", inner_html or "").strip())


def _parse_items_fallback(raw_html: str) -> list:
    """2차 fallback: corp_name 을 세그먼트 경계로 나눠, 각 세그먼트의 회사명과 첫 '상세 링크' 앵커
    (a.str_tit / a[id^=rec_link_] / relay/view href)를 결속합니다. 카드 컨테이너 클래스가 바뀌어도 동작.
    회사명을 못 찾은 세그먼트/ rec_idx 없는 세그먼트는 건너뜁니다(회사명 없는 등록 금지)."""
    marks = [m.start() for m in _CORP_NAME_MARK.finditer(raw_html)]
    items = []
    seen_rec = set()
    for i, start in enumerate(marks):
        end = marks[i + 1] if i + 1 < len(marks) else len(raw_html)
        seg = raw_html[start:end]
        corp_m = _CORP_NAME.search(seg)
        if not corp_m:
            continue
        company = html.unescape(corp_m.group(1).strip())
        if not company:
            continue
        # 세그먼트 내 첫 번째 상세 링크 앵커(회사 자체 링크는 rec_idx 가 없어 자연히 건너뜀)
        rec_idx = open_tag = inner = ""
        for am in _ANCHOR_FULL.finditer(seg):
            full = am.group(0)
            om = _A_OPEN.match(full)
            otag = om.group(0) if om else ""
            rid = _rec_idx_from_anchor(otag)
            if rid:
                rec_idx, open_tag = rid, otag
                inner = full[len(otag):-4] if full.lower().endswith("</a>") else full[len(otag):]
                break
        if not rec_idx or rec_idx in seen_rec:
            continue
        seen_rec.add(rec_idx)
        items.append({
            "company_name": company,
            "title": _title_from_anchor(open_tag, inner),
            "detail_url": canonical_detail_url(rec_idx),
            "rec_idx": rec_idx,
            "external_id": f"SARAMIN:{rec_idx}",
        })
    return items


def _scan_view_rec_idx(raw_html: str):
    """3차: relay/view href 또는 rec_link id 를 가진 a 태그 전체에서 rec_idx 를 스캔합니다(회사명 무관).
    파서가 놓친 링크 감지/로깅용. 반환: (rec_idx 집합, rec_idx 추출 실패 앵커 수)."""
    found = set()
    fail = 0
    for om in _A_OPEN.finditer(raw_html):
        otag = om.group(0)
        href_m = _HREF.search(otag)
        is_view = bool(href_m and "/zf_user/jobs/relay/view" in href_m.group(1).lower())
        is_reclink = bool(_ID_REC_LINK.search(otag))
        if not (is_view or is_reclink):
            continue
        rid = _rec_idx_from_anchor(otag)
        if rid:
            found.add(rid)
        else:
            fail += 1
    return found, fail


def collect_didim_postings(search_url: str = None) -> dict:
    """사람인 '디딤' 검색 결과를 수집하고 디딤(주) 공고만 필터링해 반환합니다.

    1차(item_recruit) + 2차(corp_name 세그먼트 fallback) 결과를 rec_idx 로 dedupe(1차 우선)하고,
    3차 링크 스캔은 파서가 놓친 rec_idx 감지/로깅용으로만 사용합니다.
    반환: {"search_url", "collected_count"(회사명 결속된 카드 수), "items"(디딤(주) 매칭만)}.
    fetch/parse 실패 시 SaraminCollectError.
    """
    url = (search_url or settings.SARAMIN_DIDIM_SEARCH_URL or "").strip()
    if not url:
        raise SaraminCollectError("사람인 검색 URL 이 설정되지 않았습니다.", "search_url_not_configured",
                                  ".env 의 SARAMIN_DIDIM_SEARCH_URL 을 확인해주세요.", status_code=500)
    try:
        _assert_safe_url(url)
        raw_html = _fetch_html(url)
    except JobExtractError as e:
        raise SaraminCollectError("사람인 검색 결과 페이지를 불러오지 못했습니다.", "search_page_fetch_failed",
                                  e.hint, status_code=502) from e

    try:
        primary = _parse_items(raw_html)
        fallback = _parse_items_fallback(raw_html)
        scan_recs, rec_fail = _scan_view_rec_idx(raw_html)
    except Exception as e:
        raise SaraminCollectError("사람인 검색 결과를 해석하지 못했습니다.", "search_page_parse_failed",
                                  "사람인 페이지 구조가 바뀌었을 수 있습니다.", status_code=502) from e

    # rec_idx 기준 dedupe — 1차(회사명/제목 정확) 우선. 단 1차 제목이 비면 2차 제목으로 보강.
    by_rec = {}
    for it in fallback:
        by_rec[it["rec_idx"]] = it
    for it in primary:
        prev = by_rec.get(it["rec_idx"])
        if prev and not (it.get("title") or "").strip() and (prev.get("title") or "").strip():
            it = {**it, "title": prev["title"]}
        by_rec[it["rec_idx"]] = it
    all_items = list(by_rec.values())

    matched = [it for it in all_items if is_didim_company(it["company_name"])]
    # 링크 스캔에서만 발견된 rec_idx(파서가 회사명 결속에 실패한 것) = 파서 갱신 필요 신호
    parser_missed = len(scan_recs - set(by_rec.keys()))
    _log(f"[saramin-collect] primary={len(primary)} fallback={len(fallback)} "
         f"deduped={len(all_items)} link_scan={len(scan_recs)} parser_missed={parser_missed} "
         f"rec_fail={rec_fail} matched_didim={len(matched)}")
    return {"search_url": url, "collected_count": len(all_items), "items": matched}
