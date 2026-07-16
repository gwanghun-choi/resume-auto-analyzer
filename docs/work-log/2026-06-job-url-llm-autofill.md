# 공고 URL 기반 LLM 자동 채우기 + JD 라벨 변경

- **작업 일시**: 2026-06-12
- **작업 목적**: ① 공고 모달 JD 필드 라벨을 회사 공고 양식에 맞게 변경(UI만), ② 플랫폼 공고 URL 페이지를 가져와 LLM 으로 공고명/플랫폼/주요업무/자격요건/우대사항을 추출해 **비어 있는 입력값만 자동 채우기**(저장은 사용자가 직접). 부서/팀은 자동 입력 제외, 대상 회사 공고만 동작.

## 변경 파일
- (신규) `app/services/job_extract_service.py` — URL 검증/SSRF 방어/HTML→text/대상 회사 검증/LLM 추출.
- (신규) `app/api/jobs_router.py` — `POST /api/jobs/extract-from-url`.
- `app/schemas/job_posting_schema.py` — `JobExtractRequest{url}`.
- `app/main.py` — `jobs_router` 등록.
- `app/templates/index.html` — JD 라벨 변경 + URL 옆 [공고 내용 가져오기] 버튼/메시지. 캐시버스트 `v46→v47`.
- `app/static/app.js` — `extractFromUrl`/`applyExtractResult` + 버튼 wiring + VIEWER 숨김 + 폼 리셋 시 메시지 초기화.

## 추가한 API 경로
- `POST /api/jobs/extract-from-url` (요청 `{url}`). 응답: `{company_verified, company_name, source_url, platform, job_title, main_tasks, qualifications, preferred, warning}`.

## 추가/변경 라이브러리
- **없음**. HTML 조회는 stdlib `urllib.request`, 파싱은 stdlib `re`/`html`, IP 검사는 `ipaddress`/`socket`. LLM 은 기존 `openai_llm_service.call_openai_json` 재사용. (requests/httpx/bs4/LangChain 미추가)

## 라벨 변경 (공고 모달 JD 카드, UI만)
- 필수 기술 → **자격 요건**(`jdRequired`), 우대 기술 → **우대 사항**(`jdPreferred`), JD 상세내용 → **주요 업무**(`jdContent`). **id/내부 필드(required_skills/preferred_skills/jd_content)·DB 컬럼·점수 계산 로직 불변.** (legacy `view-jd` 화면 라벨은 미변경)

## URL 자동 추출 처리 흐름 (백엔드)
1. 권한 검사(ADMIN/MANAGER, VIEWER 403) — URL 조회/LLM 호출 **전**.
2. URL 검증: http/https 외 차단(`invalid_scheme`).
3. **SSRF 방어**: 호스트 DNS 해석 IP 전수 검사 → private/loopback/link-local(169.254.169.254)/reserved/multicast/unspecified(0.0.0.0)/127.0.0.1/localhost 차단(`ssrf_blocked`). 리다이렉트도 매 hop 재검증(`_SafeRedirectHandler`).
4. HTML 조회(2MB 제한, 10s timeout, content-type html/text/xml 만).
5. script/style/noscript 제거 → 태그 제거 → `html.unescape` → 공백 정리(plain text).
6. **대상 회사 1차 검증**: 텍스트/원본 HTML 에 `TARGET_COMPANY_KEYWORDS` 포함 여부. 미확인 시 **LLM 미호출**, `company_verified=false` + warning 반환(입력값 미변경).
7. 확인 시 LLM(`call_openai_json`)으로 job_title/main_tasks/qualifications/preferred 추출(최대 15000자 입력). 부서 관련 값은 프롬프트에서 추출 금지.
8. platform 은 URL 도메인 기준(saramin→사람인, jobkorea→잡코리아, wanted→원티드, 그 외 null).

## 프론트 자동 채우기 정책
- [공고 내용 가져오기] 클릭 → URL 비면 안내, 처리 중 버튼 disabled + "가져오는 중...".
- 성공+verified: **비어 있는 필드만** 채움(공고명/플랫폼/주요업무/자격요건/우대사항). **부서/팀은 절대 자동 입력 안 함**. 플랫폼은 비어있을 때만 + select option 에 존재하는 값만. "공고 내용을 가져왔습니다. 내용을 확인 후 저장해주세요."
- verified=false: 어떤 필드도 덮어쓰지 않음 + warning 표시.
- 실패: "공고 내용을 가져오지 못했습니다. URL을 확인하거나 직접 입력해주세요."
- **자동 저장 없음** — 사용자가 기존 [공고 저장]/[JD 저장] 클릭 시 기존 저장/Drive/DB 로직 그대로 동작.

## 권한 / 기존 로직 영향
- 권한: ADMIN/MANAGER 호출 가능, VIEWER 403(백엔드) + 버튼 숨김(프론트). URL 조회/LLM 전에 검사.
- 기존 공고 저장 API·JD 저장(upsert_jd)·Drive 연동·DB 저장·MatchingService 점수 산식·required_skills/preferred_skills 기반 로직 **미수정**.

## 테스트 방법
```
cd <프로젝트 루트>
uv run uvicorn app.main:app --reload
# http://localhost:8000 → 공고/JD 관리 → 공고 등록 팝업 → URL 입력 → [공고 내용 가져오기]
curl -X POST "http://localhost:8000/api/jobs/extract-from-url" -H "Content-Type: application/json" -d '{"url":"https://example.com/job"}'
```

## 테스트 결과 (라이브)
- 라우트 등록 확인, `py_compile`/`node --check` 통과.
- SSRF: localhost/127.0.0.1/169.254.169.254/0.0.0.0/ftp:// 차단 확인, 공개 URL 허용.
- 플랫폼 매핑: saramin→사람인, jumpit→None(미존재 → 채우지 않음).
- HTML→text: script/style 제거 + 대상 회사 키워드 검출.
- **라이브 fetch**: `example.com`(대상 회사 아님) → fetch+parse 후 `company_verified=false` + warning, 필드 빈값, LLM 미호출. 사설 URL extract 호출 시 ssrf_blocked.
- (참고) 대상 회사 실제 공고 URL 의 LLM 추출 결과는 서버 기동 + 브라우저 v47 새로고침 후 사용자 확인 필요.

## 남은 이슈 / TODO (docs/TODO.md)
- 자격요건/우대사항이 현재 required_skills/preferred_skills(스킬 배열, 콤마/줄바꿈 split)에 bullet 문자열로 저장됨 → JD 필드/DB 컬럼 정식 리팩토링 시 free-text 분리 검토.
- 외부 플랫폼별 HTML 구조 대응/추출 정확도, 로그인 필요 공고 처리, 부서/팀 자동 매칭 정책 등.
