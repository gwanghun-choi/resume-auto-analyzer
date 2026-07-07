# 공고 수정 팝업 닫기 + 안내문구 + 미처리 이력서 요약 + JD 추출 정확도

- **작업 일시**: 2026-06-12
- **작업 목적**: ① 공고 수정 성공 후 팝업 자동 닫기, ② 통합 폼에 안 맞는 상단 안내문구 제거, ③ 이력서 업로드 영역에 해당 공고의 기존 미처리 이력서 요약 표시, ④ [공고 내용 가져오기] 시 JD 3개(자격 요건/우대 사항/주요 업무) 채우기 정확도 개선(HTML 추출 + LLM 프롬프트 강화).

## 변경 파일
- `app/templates/index.html` — 상단 안내문구 교체, 업로드 영역에 `#resumeUploadPending` 추가. 캐시버스트 `v49→v50`.
- `app/static/app.js` — `savePosting` 전체 성공 시 `closePostingModal()` 호출, `openResumeUpload`에 `loadUploadPendingSummary` 추가.
- `app/static/style.css` — `.upload-pending-summary`/`.upload-pending-list`.
- `app/services/job_extract_service.py` — `_html_to_text`(섹션/표 구조 보존) + `_build_prompt`(섹션 라벨 동의어 분류 규칙) 강화.

## 수정한 API 경로
- 신규 없음. 미처리 요약은 **기존 `GET /api/resumes/posting-pending/{id}?page=1&size=5` 재사용**(file_status=UPLOADED & analysis_status=PENDING = 미처리/분석 대기).

## 1. 공고 수정 후 팝업 닫기 (처리 위치)
- `app/static/app.js` `savePosting()` 의 성공 분기: 공고+JD 전체 성공 시 `loadJobPostings()`(목록 갱신) + `showPostingNotice(...)` + **`closePostingModal()`**(overlay hidden). 신규/수정 모두 동일. JD 저장만 실패하면 팝업 유지 + 오류 안내(불일치 인지용).

## 2. 제거한 안내 문구 (위치)
- `app/templates/index.html` `#postingModalTitle` 아래 `<p class="hint">` : "공고를 먼저 등록한 뒤 JD를 등록할 수 있습니다." → **"공고 기본정보와 JD 내용을 입력한 뒤 저장해주세요."** (통합 폼에 맞게).

## 3. 미처리 이력서 요약 (구현 방식)
- `openResumeUpload(postingId, title)` → `loadUploadPendingSummary(postingId)`: `posting-pending` API 로 총 건수+상위 5개 파일명만 표시(개인정보 최소 — 파일명/건수만, 다운로드 링크 없음). 5개 초과면 "외 N건". 미처리 0건이면 "미처리(분석 대기) 이력서가 없습니다." 기존 업로드 기능은 그대로.

## 4. JD 3개 필드 자동 채우기 정확도 (핵심)
### LLM 응답 key ↔ 화면 textarea (매핑 — 정상)
- `qualifications` → `#jdRequired`(자격 요건) → `required_skills`(JSONB 배열)
- `preferred` → `#jdPreferred`(우대 사항) → `preferred_skills`(JSONB 배열)
- `main_tasks` → `#jdContent`(주요 업무) → `jd_content`(Text)
- `job_title` → `#postingTitle`, `platform`(URL 도메인 코드) → `#postingPlatform`
- (매핑/저장 로직은 이미 정상 — 본 작업은 **추출 품질**을 올림)

### HTML→text 개선 (`_html_to_text`)
- `<head>`/주석 제거, `<br>`·블록/제목/표 시작·끝 태그(`h1~6,p,div,section,article,ul,ol,li,tr,table,dt,dd`)를 줄바꿈, `<td>/<th>`는 ` | ` 구분 → **섹션 제목(주요 업무/자격요건/우대 사항)이 줄로 분리**되고 표 셀이 안 합쳐져 LLM 인식률 향상. nbsp 정리.

### LLM 프롬프트 강화 (`_build_prompt`)
- 섹션 라벨 **동의어 분류 규칙** 명시: main_tasks←주요업무/담당업무/수행업무/직무내용, qualifications←자격요건/자격조건/지원자격/필수요건, preferred←우대사항/우대조건/우대요건. 한 줄에 한 항목·bullet 기호 없이·원문에 있으면 빈 문자열 금지·JSON만 반환·부서/플랫폼 추출 금지.

## 5·6. 통합 저장 / 저장 컬럼 (검증)
- 단일 버튼(`공고 등록`/`공고 수정`) → 공고 저장 → `_savePostingJdIfPresent`로 `POST /{id}/jd`(기존 upsert). **공고 JD 는 `resume_ai.job_posting_jds` 에 저장**(`job_postings`와 별도 테이블. legacy `job_descriptions`와 무관).
- **주요 업무 저장 컬럼 = `job_posting_jds.jd_content`(Text)**. `required_skills`/`preferred_skills` = JSONB **배열**(직전 작업 라이브 E2E 확인). DB 확인:
```sql
SELECT id, posting_id, title, required_skills, preferred_skills, jd_content
FROM resume_ai.job_posting_jds ORDER BY id DESC LIMIT 10;
```

## 테스트 방법 / 결과 (라이브, ADMIN)
```
uv run uvicorn app.main:app --reload   # http://localhost:8000 (브라우저 하드 새로고침 v50)
```
- `py_compile`/`node --check`/CSS 균형 통과.
- **HTML 추출**: 사람인류 구조(div/표/ul) 모사 → "주요 업무/자격요건/우대사항" 각각 줄 분리, 표 셀 `|` 보존, script 제거 확인. 프롬프트에 동의어(담당업무/자격조건/우대조건) 포함 확인.
- **회귀**: extract 파이프라인 정상(비-디딤 → company_verified=false, LLM 미호출), posting-pending view 형태(total/files) 정상.
- 직전 E2E: 공고+JD 통합 저장 시 `job_posting_jds`에 JSONB 배열+jd_content 저장, has_jd 반영, 수정 시 active 1건 유지.

## 남은 이슈 / 한계
- **사람인 등 일부 공고는 본문이 iframe/JS 로 렌더링**되어 정적 GET HTML 에 JD 본문이 없을 수 있음(이 경우 LLM 입력에 섹션이 없어 빈 값). 브라우저 자동화/플랫폼 전용 크롤러는 제약상 미도입 → **TODO**(정적 HTML 에 본문이 있는 공고는 개선된 추출+프롬프트로 채워짐).
- 공고+JD 저장이 프론트 순차 2-API → 단일 트랜잭션화 TODO.
