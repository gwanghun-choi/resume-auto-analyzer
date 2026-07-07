# 공고 URL 자동 채우기 → JD 영역/통합 저장 검증 및 보정

- **작업 일시**: 2026-06-12
- **작업 목적**: [공고 내용 가져오기] 후 하단 JD(자격 요건/우대 사항/주요 업무)가 채워지고 공고 등록/수정 단일 저장에 포함되는지 점검·보정. (핵심 흐름은 직전 통합 폼 작업(v48)에서 구현됨 → 본 작업은 **정합성 검증 + 표 명확화 + UX 보정**)

## 변경 파일
- `app/static/app.js` — 추출 성공 메시지에 "JD까지 확인" 문구 추가 + **채워진 JD 카드로 자동 스크롤**(상단 URL 입력에서 하단 JD 가 화면 밖일 수 있어 "안 채워진 것처럼 보이는" 문제 보정).
- `app/templates/index.html` — 캐시버스트 `v48→v49`(직전 수정 JS 가 stale 캐시로 반영 안 되는 환경 대비 강제 리로드).

## 매핑/흐름 검증 결과 (코드 + 라이브 E2E)
### LLM 응답 key → 화면 textarea (정확히 매핑됨)
- `job_title` → `#postingTitle`(공고명/JD명)
- `qualifications` → `#jdRequired`(**자격 요건**) → 저장 시 `required_skills`(JSONB 배열)
- `preferred` → `#jdPreferred`(**우대 사항**) → 저장 시 `preferred_skills`(JSONB 배열)
- `main_tasks` → `#jdContent`(**주요 업무**) → 저장 시 `jd_content`(Text 문자열)
- `platform` → `#postingPlatform`(URL 도메인 기준 코드, select option 에 있을 때만 선택)
- `applyExtractResult`/`extractFromUrl`/`savePosting`/`_savePostingJdIfPresent` 모두 **단일 정의**(중복 shadowing 없음).

### 저장 request 에 JD 포함됨
- `savePosting`(단일 버튼) → 공고 저장(POST/PUT) → `_savePostingJdIfPresent` 가 `#jdRequired`/`#jdPreferred`/`#jdContent` 를 읽어 `POST /api/job-postings/{id}/jd`(기존 upsert) 호출. `required_skills`/`preferred_skills` 는 기존 `parseSkillsInput`(콤마/줄바꿈 split)로 배열 변환.

### 저장 테이블 (중요 — 명확화)
- 공고 JD 는 **`resume_ai.job_posting_jds`** 에 저장됩니다. (`job_postings` 와 **다른 테이블** 유지 — "서로 다른 테이블" 요구 충족)
- `resume_ai.job_descriptions` 는 **legacy(부서 기준 JD)** 테이블이며 공고 JD 와 무관합니다. → DB 확인은 아래 쿼리 사용:
```sql
SELECT id, posting_id, title, required_skills, preferred_skills, jd_content
FROM resume_ai.job_posting_jds ORDER BY id DESC LIMIT 10;
```

## 구현 내용 (직전 작업 + 본 보정)
- 공고 모달: 공고 기본 정보 + JD 상세 **처음부터 함께 표시**, 저장 버튼 **하나**(신규=공고 등록 / 수정=공고 수정)로 공고+JD 함께 저장(신규: 공고 저장→posting_id→JD upsert→Drive 폴더 생성).
- 추출 후 confirm 덮어쓰기(값 있으면), 부서/팀·상태는 미변경, 플랫폼은 URL 기준. LLM bullet(`- `)·빈 줄 제거 후 줄바꿈 문자열로 textarea 채움.
- 권한: ADMIN/MANAGER 만 추출 API 호출(VIEWER 403, URL/LLM 전 검사), 저장 권한 기존 정책 유지(부서 미지정 시 역할만 검사).
- 디버그 console.log 는 추가하지 않음(요청대로 최종본에 debug log 없음 — 검증은 백엔드 E2E 로 수행).

## 테스트 방법
```
cd /mnt/d/workspace_ref/langgraph-gemini-resume-demo
uv run uvicorn app.main:app --reload   # http://localhost:8000 (브라우저 하드 새로고침으로 v49 로드)
```
공고/JD 관리 → 공고 등록 → URL 입력 → [공고 내용 가져오기](디딤 공고면 JD 3개+플랫폼 채움, 값 있으면 confirm) → 공고 등록 클릭(Network 에서 `/api/job-postings` + `/{id}/jd` 호출, JD body 포함 확인).

## 테스트 결과 (라이브 DB+Drive, ADMIN)
- `node --check` 통과, 함수 중복 정의 없음, JD 카드 hidden 미조작(항상 표시).
- **E2E**: 공고 등록 → JD 저장 시 `job_posting_jds.required_skills`/`preferred_skills` = JSONB **list**(`['해당분야 관련 경력 1~5년','전문대졸 이상']` 등), `jd_content`(주요 업무) Text 저장, 목록 `has_jd=True`. **수정(덮어쓰기)** 시 active JD 1건 유지 + 새 값 반영. (테스트 데이터/Drive 폴더 정리)
- 기존 Drive 폴더 생성/점수용 required_skills·preferred_skills 구조 불변.

## 남은 이슈
- 공고+JD 저장이 프론트 순차 2-API(공고 성공·JD 실패 가능) → 서비스 레벨 단일 트랜잭션화 검토(TODO).
- 부서 미지정 공고의 이력서 업로드(resume_files.dept_id NOT NULL) 정책(TODO).
- LLM 추출 정확도/플랫폼별 HTML 구조 대응(TODO).
