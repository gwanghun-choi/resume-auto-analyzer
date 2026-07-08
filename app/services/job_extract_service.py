import html
import ipaddress
import re
import socket
import urllib.request
from urllib.parse import urlparse, parse_qs, urljoin

from app.services.google_drive_service import _log
from app.services.openai_llm_service import call_openai_json, api_key_present, OpenAILLMError

# 공고 URL → 페이지 텍스트 추출 → (디딤(주) 공고 검증) → LLM 으로 공고 기본정보/JD 추출.
# 결과는 화면 입력값 자동 채우기 용도로만 반환합니다. (DB 저장/부서 자동선택 없음)
#
# 보안:
#  - http/https 외 scheme 차단, localhost/사설/링크로컬/예약 IP 차단(SSRF 방어), 리다이렉트도 매 hop 재검증.
#  - 응답 크기/LLM 입력 길이 제한.
#  - 민감정보(API key 등)는 로그/응답에 출력하지 않습니다.

# 디딤(주) 공고로 인정할 회사명 키워드
COMPANY_KEYWORDS = ["디딤(주)", "(주)디딤", "주식회사 디딤", "디딤"]
COMPANY_NAME = "디딤(주)"

# URL 도메인 → (플랫폼 코드, 라벨). 코드는 공고 모달 select option value 와 매칭됩니다.
# select 에 없는 코드(JUMPIT/INCRUIT/CAREER)는 프론트에서 선택하지 않고 라벨만 참고합니다.
PLATFORM_BY_DOMAIN = {
    "saramin.co.kr": ("SARAMIN", "사람인"),
    "jobkorea.co.kr": ("JOBKOREA", "잡코리아"),
    "wanted.co.kr": ("WANTED", "원티드"),
    "jumpit.co.kr": ("JUMPIT", "점핏"),
    "incruit.com": ("INCRUIT", "인크루트"),
    "career.co.kr": ("CAREER", "커리어"),
}

MAX_FETCH_BYTES = 2_000_000   # 페이지 본문 최대 2MB
MAX_LLM_CHARS = 15000         # LLM 에 넘길 텍스트 최대 길이
FETCH_TIMEOUT = 10            # 초
MAX_IFRAME_FETCH = 3          # 동일 출처 iframe 추가 fetch 최대 개수

# JD 섹션 제목 동의어 (수집 본문에 해당 섹션이 있는지 판단 + LLM 누락 검증용)
SECTION_KEYWORDS = {
    "main_tasks": ["주요 업무", "주요업무", "담당업무", "담당 업무", "수행업무", "직무내용", "업무내용"],
    "qualifications": ["자격요건", "자격 요건", "자격조건", "지원자격", "자격 사항", "필수요건", "경력요건"],
    "preferred": ["우대 사항", "우대사항", "우대 조건", "우대조건", "우대요건"],
}
# 섹션 미추출 시 debug_reason 코드
_EMPTY_REASON = {"main_tasks": "MAIN_TASKS_EMPTY",
                 "qualifications": "QUALIFICATIONS_EMPTY",
                 "preferred": "PREFERRED_EMPTY"}


class JobExtractError(Exception):
    """URL 자동 추출을 진행할 수 없는 오류. (라우터에서 step/hint JSON 으로 변환)"""
    def __init__(self, message: str, step: str, hint: str = "", status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.step = step
        self.hint = hint
        self.status_code = status_code


def _empty_result(url: str, warning: str, debug_reason: str = "COMPANY_NOT_VERIFIED") -> dict:
    return {
        "company_verified": False, "company_name": None, "source_url": url,
        "platform": None, "platform_label": None, "job_title": "",
        "posting_title": "", "recruit_field": "", "main_tasks": "",
        "qualifications": "", "preferred": "", "collector_method": None,
        "warning": warning, "debug_reason": debug_reason,
    }


def _section_present(text: str, key: str) -> bool:
    return any(kw in text for kw in SECTION_KEYWORDS[key])


def _has_sections(text: str) -> bool:
    """본문에 JD 섹션(주요 업무/자격요건/우대사항) 중 하나라도 있으면 True."""
    return any(_section_present(text, k) for k in SECTION_KEYWORDS)


# 각 줄 앞의 bullet 기호(- · * •)와 빈 줄을 제거하고 trim 한 줄바꿈 문자열로 정리합니다.
# (화면 textarea 입력값과 동일한 형태 → 저장 시 기존 parseSkillsInput 으로 JSONB 배열 변환)
_BULLET_PREFIX = re.compile(r"^[\-\*•··]\s*")


def _clean_bullets(text) -> str:
    s = _s(text)
    if not s:
        return ""
    lines = []
    for line in s.replace("\r\n", "\n").split("\n"):
        line = _BULLET_PREFIX.sub("", line.strip()).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _base_domain(host: str) -> str:
    """호스트에서 'saramin.co.kr' 같은 끝 도메인 후보를 만듭니다(서브도메인 무시)."""
    host = (host or "").lower().lstrip(".")
    parts = host.split(".")
    # co.kr/or.kr 등 2단계 TLD 고려: 끝 3개를 우선 시도
    if len(parts) >= 3:
        return ".".join(parts[-3:])
    return host


def _platform_for_host(host: str):
    """URL 호스트 → (플랫폼 코드, 라벨). 매칭 없으면 (None, None)."""
    h = (host or "").lower()
    base = _base_domain(host)
    for domain, (code, label) in PLATFORM_BY_DOMAIN.items():
        if base == domain or h == domain or h.endswith("." + domain):
            return code, label
    return None, None


def platform_code_for_url(url: str):
    """공고 URL → platform_code(SARAMIN/JOBKOREA/...). 매핑되는 도메인이 없으면 None(기존 기본값 유지).

    수동 공고 등록/URL 추출/배치가 URL 도메인만 보고 플랫폼을 일관되게 판정하기 위한 단일 진입점입니다.
    (예: saramin.co.kr→SARAMIN, jobkorea.co.kr→JOBKOREA, 그 외→None)
    """
    try:
        host = urlparse(url or "").hostname
    except ValueError:
        return None
    code, _ = _platform_for_host(host)
    return code


def _assert_safe_url(url: str):
    """scheme/host 검증 + 호스트가 해석되는 모든 IP 가 공인 IP 인지 확인(SSRF 방어). 실패 시 JobExtractError."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise JobExtractError("http/https URL만 허용됩니다.", "invalid_scheme",
                              "http:// 또는 https:// 로 시작하는 공고 URL을 입력해주세요.")
    host = p.hostname
    if not host:
        raise JobExtractError("URL에서 호스트를 찾을 수 없습니다.", "invalid_url",
                              "공고 페이지의 전체 URL을 입력해주세요.")
    # 명시 차단 + DNS 해석 IP 전수 검사
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise JobExtractError("URL 호스트를 확인할 수 없습니다.", "dns_failed",
                              "공고 URL을 다시 확인해주세요.")
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise JobExtractError("내부/사설 네트워크 주소에는 접근할 수 없습니다.", "ssrf_blocked",
                                  "외부 채용 플랫폼의 공개 공고 URL을 입력해주세요.")
    return p


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """리다이렉트 대상도 매 hop 마다 SSRF 검증합니다."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_html(url: str) -> str:
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; ResumeAI-JobExtract/1.0)",
        "Accept-Language": "ko,en;q=0.8",
    })
    try:
        with opener.open(req, timeout=FETCH_TIMEOUT) as resp:
            ctype = (resp.headers.get_content_type() or "").lower()
            if "html" not in ctype and "xml" not in ctype and "text" not in ctype:
                raise JobExtractError("HTML 페이지가 아닙니다.", "not_html",
                                      "채용 공고 웹페이지 URL을 입력해주세요.")
            raw = resp.read(MAX_FETCH_BYTES)
            charset = resp.headers.get_content_charset() or "utf-8"
    except JobExtractError:
        raise
    except Exception as e:
        # 네트워크/타임아웃/HTTP 오류 — 상세는 사용자에게 노출하지 않음(민감정보 방지)
        raise JobExtractError("공고 페이지를 불러오지 못했습니다.", "fetch_failed",
                              "URL이 올바른지, 로그인 없이 열리는 공개 공고인지 확인해주세요.",
                              status_code=502) from e
    return raw.decode(charset, errors="replace")


def _html_to_text(html_str: str) -> str:
    s = re.sub(r"<(script|style|noscript|head)[^>]*>.*?</\1>", " ", html_str,
               flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.DOTALL)         # 주석 제거
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    # 블록/제목/표 시작·끝 태그를 줄바꿈으로 — 섹션 제목(주요 업무/자격요건/우대 사항)이 줄로 분리되도록
    s = re.sub(r"</?(h[1-6]|p|div|section|article|ul|ol|li|tr|table|dt|dd)[^>]*>",
               "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</(td|th)>", " | ", s, flags=re.IGNORECASE)   # 표 셀 구분 보존
    s = re.sub(r"<[^>]+>", " ", s)            # 남은 태그 제거
    s = html.unescape(s)
    s = re.sub(r"[ \t ]+", " ", s)
    s = re.sub(r"\n[ \t]*", "\n", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


def _build_prompt(text: str) -> str:
    return (
        "다음은 디딤(주)의 채용 공고 웹페이지에서 추출한 평문 텍스트입니다.\n"
        "이 텍스트에서 채용 정보를 아래 JSON 형식으로만 추출하세요.\n\n"
        "반드시 지켜야 할 규칙:\n"
        "1. 아래 4개 key 만 가진 JSON 객체 하나만 반환합니다. JSON 외 설명 문장은 절대 포함하지 마세요.\n"
        "2. 원문에 없는 내용을 지어내지 마세요. 원문 표현을 최대한 유지합니다.\n"
        "3. 부서/팀/department 관련 값은 추출하지 마세요. 플랫폼도 추출하지 마세요.\n"
        "4. 섹션 제목 표현이 다양합니다. 아래 동의어를 모두 같은 항목으로 분류하세요.\n"
        "   - main_tasks    ← '주요 업무', '주요업무', '담당업무', '담당 업무', '수행업무', '직무내용', '업무내용'\n"
        "   - qualifications ← '자격요건', '자격 요건', '자격조건', '지원자격', '자격 사항', '필수요건', '경력요건'\n"
        "   - preferred     ← '우대 사항', '우대사항', '우대 조건', '우대조건', '우대요건'\n"
        "5. main_tasks/qualifications/preferred 는 줄바꿈으로 구분된 문자열로 작성합니다. 한 줄에 항목 하나, 줄 앞에 '-' 같은 bullet 기호는 붙이지 마세요.\n"
        "6. 해당 섹션 내용이 원문에 **있으면 반드시 채우고**(빈 문자열 금지), 원문에 정말 없을 때만 빈 문자열(\"\")로 둡니다.\n"
        "7. job_title 은 채용공고 상단 제목(예: 'IDC 인프라 운영 엔지니어 채용')입니다.\n"
        "   '모집분야' 값(예: 'IDC 인프라 엔지니어')은 job_title 로 쓰지 마세요. 상단 제목을 찾지 못한 경우에만 모집분야를 fallback 으로 사용합니다.\n\n"
        "반환 형식(값 형태 예시):\n"
        "{\n"
        '  "job_title": "IDC 인프라 운영 엔지니어 채용",\n'
        '  "main_tasks": "On-Premise 환경 장애 대응 및 기술 지원\\n서버 HW 구축, 반납, 증설",\n'
        '  "qualifications": "해당분야 관련 경력 1~5년\\n전문대졸 이상",\n'
        '  "preferred": "관련 자격증 보유자\\nCloud 플랫폼 운영 경험"\n'
        "}\n\n"
        "공고 텍스트:\n"
        f"{text}"
    )


def _s(v) -> str:
    return str(v).strip() if v is not None else ""


# ----- 공고 상단 제목(공고명/JD명) 추출 -----
# 공고명/JD명에는 "모집분야"(예: IDC 인프라 엔지니어)가 아니라 공고 상세 상단 제목
# (예: IDC 인프라 운영 엔지니어 채용)을 우선 사용합니다. 상단 제목은 og:title/<title> 에 들어 있어
# 정적으로 추출 가능합니다. 사이트명/마감 D-day/회사명 대괄호 등 불필요한 suffix 는 제거합니다.
_SITE_NAMES = "사람인|잡코리아|원티드|점핏|인크루트|커리어|saramin|jobkorea|wanted|jumpit|incruit|career"
_SITE_SUFFIX = re.compile(r"\s*[-|]\s*(?:" + _SITE_NAMES + r")\s*$", re.IGNORECASE)
# 마감 D-day/상시/마감일 등 제목 끝 괄호 메타 (제목 본문의 괄호는 보존하기 위해 끝부분만)
_DDAY_SUFFIX = re.compile(
    r"\s*\((?:D[\-‐‑‒–]?\s?\d+|오늘마감|내일마감|상시\s*채용|상시모집|수시채용|채용\s*시\s*마감|마감[^)]*|~[^)]*)\)\s*$"
)
_COMPANY_PREFIX = re.compile(r"^\s*\[[^\]]*\]\s*")   # [디딤(주)] 같은 회사명 대괄호 prefix


def _clean_title(raw) -> str:
    t = html.unescape(_s(raw))
    if not t:
        return ""
    prev = None
    while prev != t:   # 사이트명/D-day suffix 가 순서 무관하게 모두 제거되도록 반복
        prev = t
        t = _SITE_SUFFIX.sub("", t).strip()
        t = _DDAY_SUFFIX.sub("", t).strip()
    t = _COMPANY_PREFIX.sub("", t).strip()
    return t


def _meta_content(raw_html: str, prop: str) -> str:
    """<meta property|name="prop" content="..."> 의 content 값(속성 순서 무관)."""
    for tag in re.findall(r"<meta\s+[^>]*>", raw_html, re.IGNORECASE):
        if re.search(r'(?:property|name)\s*=\s*["\']' + re.escape(prop) + r'["\']', tag, re.IGNORECASE):
            m = re.search(r'content\s*=\s*["\']([^"\']*)["\']', tag, re.IGNORECASE)
            if m:
                return m.group(1)
    return ""


def _title_tag(raw_html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
    return m.group(1) if m else ""


def _extract_posting_title(raw_html: str) -> str:
    """공고 상세 상단 제목을 정적으로 추출(og:title → document title). 실패 시 빈 문자열."""
    for raw in (_meta_content(raw_html, "og:title"), _title_tag(raw_html)):
        title = _clean_title(raw)
        if title:
            return title
    return ""


# ----- JD 본문 수집 (fallback 구조) -----
def _saramin_detail_url(p):
    """사람인 공고 상세 본문(iframe 내용)의 URL. JD 본문은 메인 페이지가 아니라
    /zf_user/jobs/relay/view-detail?rec_idx=... 에 정적으로 존재합니다. (사람인만)"""
    host = (p.hostname or "").lower()
    if not (host == "saramin.co.kr" or host.endswith(".saramin.co.kr")):
        return None
    rec = parse_qs(p.query or "").get("rec_idx")
    if not rec:
        return None
    return f"{p.scheme}://{p.netloc}/zf_user/jobs/relay/view-detail?rec_idx={rec[0]}"


def _same_origin_iframe_urls(raw_html: str, base_url: str, base_host: str) -> list:
    """본문 HTML 의 iframe src 중 '동일 호스트' 절대/상대 URL만 추려 반환(SSRF/외부 호출 최소화)."""
    out = []
    for src in re.findall(r'<iframe[^>]*\ssrc=["\']([^"\']+)["\']', raw_html, re.IGNORECASE):
        src = src.strip()
        if not src or src.lower().startswith(("about:", "javascript:", "data:")):
            continue
        absolute = urljoin(base_url, src)
        h = (urlparse(absolute).hostname or "").lower()
        if h and (h == base_host or h.endswith("." + base_host) or base_host.endswith("." + h)):
            out.append(absolute)
        if len(out) >= MAX_IFRAME_FETCH:
            break
    return out


def _collect_jd_text(url, p, raw_html, main_text):
    """JD 섹션이 포함된 본문 텍스트를 단계적으로 수집합니다.
    반환: (jd_text, collector_method, collect_reason)
    1) 메인 정적 HTML 본문 → 2) 사람인 상세 iframe(정적) → 3) 동일 출처 iframe(정적).
    (JS 렌더링 전용 페이지는 정적 수집 한계 — Playwright fallback 은 운영 부담으로 미도입, docs/TODO 참고)
    """
    if _has_sections(main_text):
        return main_text, "STATIC_HTML", None

    # 2) 사람인: 상세 본문 iframe URL 을 직접 정적 fetch
    detail_url = _saramin_detail_url(p)
    if detail_url:
        try:
            _assert_safe_url(detail_url)
            detail_text = _html_to_text(_fetch_html(detail_url))
            if _has_sections(detail_text):
                return (main_text + "\n" + detail_text).strip(), "SARAMIN_DETAIL", None
        except JobExtractError as e:
            _log(f"[job-extract] saramin detail fetch 실패 step={e.step}")

    # 3) 동일 출처 iframe 정적 fetch
    base_host = (p.hostname or "").lower()
    for ifr in _same_origin_iframe_urls(raw_html, url, base_host):
        try:
            _assert_safe_url(ifr)
            ifr_text = _html_to_text(_fetch_html(ifr))
            if _has_sections(ifr_text):
                return (main_text + "\n" + ifr_text).strip(), "IFRAME", None
        except JobExtractError:
            continue

    # 섹션을 못 찾음 → 메인 본문으로 best-effort 진행(원인 코드 남김)
    return main_text, "STATIC_HTML", "STATIC_HTML_SECTION_NOT_FOUND"


def extract_from_url(url: str) -> dict:
    """공고 URL 에서 (디딤(주) 검증 후) 공고 기본정보/JD 를 수집·LLM 구조화합니다.
    디딤(주) 공고가 아니면 company_verified=false 로 반환하고 LLM 을 호출하지 않습니다.
    JD 섹션이 원문에 있는데 추출이 비면 warning/debug_reason 으로 알립니다(조용한 성공 금지).
    """
    if not api_key_present():
        raise JobExtractError("OPENAI_API_KEY가 설정되어 있지 않습니다.", "openai_api_key_missing",
                              ".env 에 OPENAI_API_KEY 설정 후 서버를 재시작해주세요.", status_code=500)
    p = _assert_safe_url(url)
    raw_html = _fetch_html(url)
    main_text = _html_to_text(raw_html)
    platform_code, platform_label = _platform_for_host(p.hostname)

    # 1차 검증: 디딤(주) 공고인지 (메인 텍스트/원본 HTML 어디든 회사명 포함)
    verified = any(kw in main_text for kw in COMPANY_KEYWORDS) or any(kw in raw_html for kw in COMPANY_KEYWORDS)
    if not verified:
        return _empty_result(url, "디딤(주) 공고로 확인되지 않아 자동 입력하지 않았습니다.", "COMPANY_NOT_VERIFIED")

    # JD 본문 수집 (정적 HTML → 사람인 상세 iframe → 동일 출처 iframe)
    jd_text, collector_method, collect_reason = _collect_jd_text(url, p, raw_html, main_text)

    # LLM 구조화 (platform 은 LLM 이 아니라 URL 도메인 기준)
    try:
        parsed = call_openai_json(_build_prompt(jd_text[:MAX_LLM_CHARS]))
    except OpenAILLMError as e:
        raise JobExtractError("공고 내용을 분석하지 못했습니다.", e.step, e.hint, status_code=502) from e

    fields = {
        "main_tasks": _clean_bullets(parsed.get("main_tasks")),
        "qualifications": _clean_bullets(parsed.get("qualifications")),
        "preferred": _clean_bullets(parsed.get("preferred")),
    }
    # 검증: 원문(jd_text)에 섹션이 있는데 LLM 결과가 비면 경고(조용히 성공 처리 금지)
    missing = [k for k in fields if not fields[k] and _section_present(jd_text, k)]
    label = {"main_tasks": "주요 업무", "qualifications": "자격 요건", "preferred": "우대 사항"}
    warning = None
    debug_reason = collect_reason
    if missing:
        warning = "다음 항목을 추출하지 못했습니다: " + ", ".join(label[k] for k in missing)
        debug_reason = _EMPTY_REASON[missing[0]]
    # 공고명/JD명: 공고 상단 제목(og:title/document title) 우선, 없으면 LLM 추출값(본문 제목/모집분야) fallback.
    # 모집분야 값은 상단 제목을 찾지 못한 경우에만(=llm_title) 쓰이도록 우선순위를 둡니다.
    posting_title = _extract_posting_title(raw_html)
    llm_title = _s(parsed.get("job_title"))
    job_title = posting_title or llm_title
    _log(f"[job-extract] collector={collector_method} missing={missing or '-'} reason={debug_reason or '-'} "
         f"title_src={'POSTING' if posting_title else ('LLM' if llm_title else '-')}")

    return {
        "company_verified": True,
        "company_name": COMPANY_NAME,
        "source_url": url,
        "platform": platform_code,
        "platform_label": platform_label,
        "job_title": job_title,
        "posting_title": posting_title,   # 공고 상단 제목(참고)
        "recruit_field": llm_title,        # 모집분야/LLM 본문 제목(참고) — 공고명 우선 사용 금지
        "main_tasks": fields["main_tasks"],
        "qualifications": fields["qualifications"],
        "preferred": fields["preferred"],
        "collector_method": collector_method,
        "warning": warning,
        "debug_reason": debug_reason,
    }
