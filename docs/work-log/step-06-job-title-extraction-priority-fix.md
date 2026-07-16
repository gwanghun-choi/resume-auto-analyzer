# Step 06 — 공고명/JD명 추출 우선순위 수정 (모집분야 → 공고 상단 제목)

- **작업 일시**: 2026-06-15
- **작업 목적**: 플랫폼 공고 URL 자동 채우기에서 공고명/JD명에 **"모집분야"**(예: `IDC 인프라 엔지니어`)가 들어가던 문제를, **공고 상세 상단 제목**(예: `인프라 운영 엔지니어 채용`)을 우선 사용하도록 수정.

## 원인
- 기존 `job_title` 은 전적으로 LLM 결과(`parsed["job_title"]`)였고, LLM 입력 본문(`main_text + 상세 iframe`)에 "모집분야 IDC 인프라 엔지니어"가 포함되어 LLM 이 이를 제목으로 선택했음.
- 실제 공고 상단 제목은 `og:title`/`<title>` 에 정적으로 존재: `[샘플(주)] 인프라 운영 엔지니어 채용(D-28) - 사람인`.

## 변경 파일
- `app/services/job_extract_service.py`
  - `_extract_posting_title(raw_html)` 추가 — `og:title` → `<title>` 순으로 상단 제목 정적 추출.
  - `_clean_title()` — 사이트명 suffix(`- 사람인`/`| 잡코리아` 등), 마감 D-day suffix(`(D-28)`, `(오늘마감)` 등), 회사명 대괄호 prefix(`[샘플(주)]`) 제거. 제목 본문의 괄호(`(정규직)` 등)는 보존.
  - `_meta_content()`/`_title_tag()` 헬퍼 추가.
  - `extract_from_url()`: `job_title = posting_title or llm_title` (상단 제목 우선, 없으면 LLM 추출값=모집분야 fallback). 응답에 `posting_title`(상단 제목)·`recruit_field`(모집분야/LLM 본문 제목, 참고용) 추가. 로그에 `title_src=POSTING|LLM` 표기.
  - `_build_prompt()`: job_title 규칙 명시 — "채용공고 상단 제목"을 쓰고 "모집분야"는 상단 제목을 못 찾은 경우에만 fallback.
- 프론트엔드 변경 없음: `applyExtractResult` 가 이미 `d.job_title → #postingTitle` 매핑 + 덮어쓰기 confirm(`EXTRACT_TARGET_IDS` 에 `postingTitle` 포함) 적용 중. 백엔드 `job_title` 값만 상단 제목으로 바뀜.

## 공고명(job_title) 추출 우선순위
1. **공고 상세 상단 제목** — `og:title` (정적). 예: `인프라 운영 엔지니어 채용`
2. **document title** — `<title>` (정적). 사이트명/마감 suffix 제거.
3. (렌더링 DOM 제목 영역 — Playwright 미도입이라 현재 미사용)
4. **LLM 추출 job_title** — 위에서 못 찾은 경우 fallback.
5. **모집분야** — 최후 fallback(=LLM 이 본문 모집분야를 반환한 경우). `recruit_field` 로 분리 보관, 공고명 우선 사용 금지.

## 응답 필드(추가)
- `job_title`: 최종 공고명/JD명 (상단 제목 우선).
- `posting_title`: 공고 상단 제목(참고).
- `recruit_field`: 모집분야/LLM 본문 제목(참고) — 공고명 우선 사용 안 함.

## 테스트 결과
- 단위(`_clean_title`):
  - `[샘플(주)] 인프라 운영 엔지니어 채용(D-28) - 사람인` → `인프라 운영 엔지니어 채용`
  - `IDC 인프라 운영 엔지니어 채용 - 사람인` → `인프라 운영 엔지니어 채용`
  - `[샘플(주)] 백엔드 개발자 (정규직) 모집(오늘마감) | 잡코리아` → `백엔드 개발자 (정규직) 모집` (내부 `(정규직)` 보존)
- 라이브(테스트 URL `rec_idx=53886522`, ADMIN):
  - `job_title='IDC 인프라 운영 엔지니어 채용'` ✓, `posting_title` 동일, `recruit_field='IDC 인프라 엔지니어'`(모집분야, 미사용).
  - `collector_method=SARAMIN_DETAIL`, `title_src=POSTING`, `warning=None`.
  - JD 3개 영향 없음: main_tasks(229자)/qualifications(90자)/preferred(315자) 정상.
- `py_compile`/import 통과. JSONB 저장 구조·통합 저장·Drive·OpenAI 인증 미변경.
