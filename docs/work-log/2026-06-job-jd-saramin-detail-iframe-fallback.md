# 사람인 JD 자동 채우기 — 상세 iframe fallback 수집 + 수집 실패 reason code

- **작업 일시**: 2026-06-12
- **작업 목적**: 사람인 디딤(주) 공고 URL 에서 JD 3개(주요 업무/자격 요건/우대 사항)가 채워지지 않던 문제 해결. JD 본문이 메인 페이지가 아니라 **JS 로 로드되는 iframe(`relay/view-detail`)** 에 있음을 확인하고, **정적 fetch fallback**으로 수집하도록 수집 구조를 개선.

## 핵심 원인 / 해결 (Playwright 미도입)
- 진단: `https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=...` 의 **정적 HTML(388KB)** 에는 "디딤"은 있으나 **주요 업무/자격요건/우대사항이 없음**(상세 본문은 `about:blank` iframe 에 JS 로 주입).
- 발견: JD 본문은 **`/zf_user/jobs/relay/view-detail?rec_idx=...`** (12.5KB, **정적으로 fetch 가능**)에 그대로 존재 → 주요 업무/자격요건/우대사항 모두 포함.
- 결론: **Playwright/Selenium 불필요.** 상세 iframe URL 을 정적 fetch 하는 fallback 으로 목표 달성(가볍고 Docker/이미지 변경 없음). → pyproject/Dockerfile 변경 없음.

## 변경 파일
- `app/services/job_extract_service.py` — 수집 fallback 구조(`_collect_jd_text`) + 사람인 상세 URL(`_saramin_detail_url`) + 동일 출처 iframe(`_same_origin_iframe_urls`) + 섹션 존재 검증(`_has_sections`/`SECTION_KEYWORDS`) + `collector_method`/`warning`/`debug_reason` 응답.
- `app/static/app.js` — extract 결과에 `warning` 이 있으면(섹션 present-but-empty) 성공이 아닌 **경고**로 안내(채운 값은 유지).
- `app/static/style.css` — `.text-warning`.
- `app/templates/index.html` — 캐시버스트 `v50→v51`.

## 수정한 API 경로
- 신규 없음. 기존 `POST /api/jobs/extract-from-url` 응답에 **`collector_method`, `debug_reason`** 추가(권장 응답 구조 충족).

## 수집 fallback 구조 (`_collect_jd_text`)
1. **STATIC_HTML** — 메인 페이지 본문에 JD 섹션(주요 업무/자격요건/우대사항 동의어)이 있으면 그대로 사용.
2. **SARAMIN_DETAIL** — 사람인이고 메인에 섹션이 없으면 `relay/view-detail?rec_idx=` 를 **정적 fetch**(SSRF 재검증) → 섹션 확인 후 사용.
3. **IFRAME** — 그 외엔 본문의 **동일 출처** iframe src(절대/상대, about:blank 제외, 최대 3개)를 정적 fetch → 섹션 확인.
4. 못 찾으면 메인 본문으로 best-effort + `debug_reason=STATIC_HTML_SECTION_NOT_FOUND`.
- (JS 전용 렌더링 페이지는 정적 수집 한계 → Playwright 는 운영 부담으로 미도입, 필요 시 TODO)

## LLM 구조화 + 수집 실패 검증
- 수집 본문을 LLM 으로 `job_title/main_tasks/qualifications/preferred` JSON 구조화(프롬프트에 섹션 동의어 분류 규칙: 담당업무/자격조건/우대조건 등).
- **조용한 성공 금지**: 본문(jd_text)에 섹션이 있는데 LLM 결과가 비면 `warning`("…를 추출하지 못했습니다") + `debug_reason`(MAIN_TASKS_EMPTY/QUALIFICATIONS_EMPTY/PREFERRED_EMPTY). 프론트는 이때 성공이 아닌 경고로 표시.
- reason code: COMPANY_NOT_VERIFIED / STATIC_HTML_SECTION_NOT_FOUND / MAIN_TASKS_EMPTY / QUALIFICATIONS_EMPTY / PREFERRED_EMPTY 등. 내부 `_log` 는 collector/missing/reason 만(URL·키 등 민감정보 미출력).

## 프론트 매핑 / 저장 (이미 정상 — 재확인)
- `response.main_tasks → #jdContent(주요 업무)`, `qualifications → #jdRequired(자격 요건)`, `preferred → #jdPreferred(우대 사항)`, `job_title → #postingTitle`, `platform → #postingPlatform`(코드, option 매칭 시).
- 단일 버튼(`공고 등록`/`공고 수정`) → 공고 저장 후 `_savePostingJdIfPresent` 로 `POST /{id}/jd`. 자격요건/우대사항 textarea(줄바꿈) → `required_skills`/`preferred_skills` JSONB **배열**, 주요 업무 → **`jd_content`**(Text). **공고 JD 는 `resume_ai.job_posting_jds`**(job_postings 와 별도 테이블; legacy `job_descriptions` 아님). 수정 전체 성공 시 팝업 닫힘 + 목록 reload.

## 보안 / 권한 (유지)
- SSRF 방어: http(s) 외·localhost·127.0.0.1·0.0.0.0·169.254.169.254·사설/예약 IP 차단, 리다이렉트 hop 재검증. 상세/iframe fetch 도 `_assert_safe_url` 재검증, **동일 출처만**, 추가 fetch 최대 3개. 권한 ADMIN/MANAGER(VIEWER 403, URL/LLM 전 검사). 민감정보 미출력.

## 테스트 방법 / 결과
```
uv run uvicorn app.main:app --reload   # http://localhost:8000 (브라우저 하드 새로고침 v51)
```
- **라이브(테스트 URL `rec_idx=53886522`, ADMIN)**: `company_verified=true`, **`collector_method=SARAMIN_DETAIL`**, `job_title="IDC 인프라 엔지니어"`, **main_tasks/qualifications/preferred 3개 모두 채워짐**(주요 업무 7항목/자격요건 4항목/우대사항 8항목, bullet 제거), `warning=None`.
- 회귀: 비-디딤(example.com) → `company_verified=false`, `debug_reason=COMPANY_NOT_VERIFIED`, LLM 미호출. `py_compile`/`node --check`/CSS 균형 통과.
- DB 확인(공고+JD 저장): `SELECT id, posting_id, title, required_skills, preferred_skills, jd_content FROM resume_ai.job_posting_jds ORDER BY id DESC LIMIT 10;` (required/preferred=JSONB 배열, 주요 업무=jd_content — 직전 작업 E2E 확인).

## 남은 이슈 / 운영 고려
- JS 전용 렌더링(정적·iframe 모두 본문 없음) 공고는 현재 수집 불가 → 필요 시 Playwright/Selenium fallback(이미지 크기/빌드시간/메모리·Dockerfile chromium 설치 부담) 검토 = TODO. 현재 사람인은 정적 상세 fetch 로 충족.
- 플랫폼별 상세 URL/HTML 구조 대응(잡코리아/원티드 등) 추가, 공고+JD 단일 트랜잭션화.
