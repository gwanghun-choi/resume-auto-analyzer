# [2026-07-07] 3차 — 사람인 URL 수집 파서 fallback 보강

## 1. 작업 배경

사람인 신규 공고 수집(1·2차)의 뒤 흐름(신규 insert → posting_id 큐 적재 → JD 분석 worker)은 정상이지만, **검색 결과 HTML 파서**가 `item_recruit`/`corp_name`/`job_tit` 정규식에 의존해 카드 컨테이너 클래스가 바뀌면 수집 0건이 될 수 있었다. 사용자가 확인한 실제 DOM 예시는 `a.str_tit` / `id="rec_link_..."` / `href="...rec_idx=..."` 구조였다. 이번 3차는 **정적 HTML 기반 fallback 보강**까지만 진행한다(Playwright/Selenium 제외).

## 2. 기존 문제

- `_parse_items` 는 `div.item_recruit` 로 카드를 나눈 뒤 그 안에서 `corp_name`/`job_tit`/view href 를 찾음 → **`item_recruit` 클래스가 없으면 0건**.
- 제목은 `job_tit > a[title]` 에서만 추출 → 다른 제목 구조(`str_tit`/span)면 제목 누락.

## 3. 보강한 fallback (모두 정적 정규식, 새 의존성 없음)

기존 정상 동작(디딤(주) exact 필터, rec_idx 기반 `canonical_detail_url`, tracking 제거, normalized URL 중복 판단, posting_id 큐 적재)은 **변경하지 않았다.** 파서 파싱만 3단계로 견고화:

1. **1차 `_parse_items`(유지)**: 기존 `item_recruit` 카드 + `corp_name` + `job_tit`/view href.
2. **2차 `_parse_items_fallback`(신규)**: `corp_name` 을 세그먼트 경계로 나눠, 각 세그먼트의 회사명과 첫 상세 링크 앵커(`a.str_tit` / `a[id^=rec_link_]` / `relay/view href`)를 **결속**. 카드 컨테이너 클래스가 바뀌어도 동작. 회사명 못 찾거나 rec_idx 없는 세그먼트는 건너뜀.
   - rec_idx 추출 우선순위: ① href query string `rec_idx` ② `id="rec_link_숫자"` (`_rec_idx_from_anchor`).
   - 제목 우선순위: ① a `title` 속성 ② 내부 `span` text ③ a 내부 text ④ ''(호출측 `(제목 미상)` 처리) (`_title_from_anchor`).
3. **3차 `_scan_view_rec_idx`(신규)**: `relay/view href` 또는 `rec_link id` 를 가진 a 태그 전체 스캔(회사명 무관). **파서가 놓친 rec_idx 감지/로깅용** — 회사명을 결속하지 못한 링크는 **등록하지 않음**(false positive 금지).

**dedupe**: 1·2차 결과를 `rec_idx` 기준으로 합치되 **1차 우선**(회사명/제목이 더 정확). 단 1차 제목이 비면 2차 제목으로 보강.

## 4. rec_idx / URL 정규화 기준 (기존 유지)

- raw href `/zf_user/jobs/relay/view?view_type=list&rec_idx=53660011&adsCategoryItem=effect_bold`
- → normalized `https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=53660011` (`canonical_detail_url`, tracking·view_type 제거, rec_idx 만 유지, `SARAMIN_BASE` 절대 URL). 중복 비교는 normalized URL/rec_idx 기준.

## 5. 회사명 필터 기준 (기존 유지, fallback 에서도 준수)

- `normalize_company`(모든 공백 제거) 후 `{"디딤(주)", "디딤주식회사"}` exact 매칭만 통과 → 디딤(주)/디딤 (주)/디딤 주식회사 허용.
- 제외: 디딤 정신건강의학과의원, (주)디딤 커뮤니케이션/센서/컴퍼니 등.
- **fallback 에서도 회사명은 항상 `corp_name` 에서 결속** → 회사명 확인이 안 되면 등록하지 않음(false negative 선호). 링크만으로 등록하지 않음.

## 6. 변경 파일

- `app/services/saramin_job_collect_service.py` — fallback 정규식/헬퍼(`_rec_idx_from_anchor`, `_title_from_anchor`, `_parse_items_fallback`, `_scan_view_rec_idx`) 추가, `collect_didim_postings` 를 1·2·3차 + dedupe + 로깅으로 보강. (`_parse_items`/필터/정규화/반환 shape 불변)
- `docs/TODO.md` / `docs/WORKFLOW.md` — 최소 반영. 본 work-log.
- (Celery/이력서 분석/JD worker/OpenAI/Drive/DB/프론트/스케줄러 **변경 없음**)

## 7. 검증 결과

### mock HTML (8케이스, read-only)
- 케이스1 기존 `item_recruit`+`corp_name`+`job_tit` → 정상 수집(rec 100).
- 케이스2 `str_tit`+`rec_link` 구조 → company=디딤 (주), title=`2026 각 부문 신입/경력 수시채용`, rec_idx=53660011, detail_url 정규화 확인.
- 케이스3 `(주)디딤 커뮤니케이션` → 제외.
- 케이스4 tracking(adsCategoryItem/view_type) 제거 → `...view?rec_idx=53660011`.
- 케이스5 `item_recruit` 없는 카드 → 2차 fallback 이 수집(primary=0, fallback=1, rec 777).
- 케이스6 회사명 없는 링크만 → 미등록(collected=0, `parser_missed=1` 로깅).
- 케이스7 같은 rec_idx 가 1·2차 양쪽 → 1건으로 dedupe.
- 케이스8 `job_tit`/title 없이 `span` 제목만 → 제목 span fallback(`데이터 엔지니어`), 회사명 결속.
- 전 케이스 PASS. `compileall` OK, `import app.main` OK.

### 라이브 dry-run (실제 검색 URL, read-only — DB insert/큐 enqueue 없음)
- 대상: `https://www.saramin.co.kr/zf_user/search?searchword=%EB%94%94%EB%94%A4&...`
- 결과: **collected=0, matched=0**. 원인 진단(마커 카운트만, 전문 로그 금지): HTML 1.99MB, `<title>디딤 통합검색 | 총 387건의 검색결과 - 사람인</title>` (실제 페이지·차단/캡차 아님)인데 `item_recruit`/`str_tit`/`rec_link_`/`rec_idx=`/`/zf_user/jobs/relay/view`/`corp_name` **전부 0개**.
- 결론: **검색 결과 목록이 JS(클라이언트)로 렌더링**되어 정적 HTML 에 상세 링크가 존재하지 않음. 정적 파서 fallback 로는 없는 링크를 만들 수 없음 → 라이브 정적 수집은 0건이 정상적 한계. (파서 결함 아님)
- 보강한 fallback 은 마크업이 정적으로 존재할 때(서버 렌더 조건 또는 향후 렌더링 DOM 을 이 파서에 공급할 때) 정확히 동작함을 mock 으로 검증함.

## 8. 남은 작업

- **[중요] 브라우저 렌더링 DOM fallback(Playwright/Selenium)**: 라이브 검색 결과가 JS 렌더링이라 실제 수집에는 렌더링 DOM 이 필요(이번 범위 제외). 도입 시 Docker chromium/이미지 크기/빌드/실행 검토. 렌더링된 HTML 을 그대로 이 파서(1·2·3차)에 넘기면 재사용 가능.
- 사람인 HTML 구조 변경 모니터링: `parser_missed`/`link_scan`/`rec_fail` 로그로 감지.
- (참고) 서버 렌더 검색 endpoint/파라미터가 있는지 여부는 별도 조사 대상(이번 범위 밖).
