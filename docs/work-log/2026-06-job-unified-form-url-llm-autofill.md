# 공고/JD 통합 입력 폼 + 단일 저장 + URL 자동 채우기(JD 포함) 개선

- **작업 일시**: 2026-06-12
- **작업 목적**: ① 부서/팀 선택사항화, ② 공고 모달에서 JD 카드를 처음부터 표시(통합 입력), ③ 저장 버튼 단일화(신규=공고 등록 / 수정=공고 수정, 한 번에 공고+JD 저장), ④ [공고 내용 가져오기]가 공고명뿐 아니라 JD(주요 업무/자격 요건/우대 사항)·플랫폼까지 채우도록 수정, ⑤ 이미 값이 있으면 confirm 후 덮어쓰기.

## 변경 파일
- (DB) `docs/sql/2026-06-12-job-postings-dept-nullable.sql` — `job_postings.department_id` **DROP NOT NULL**(resume_ai, 적용 완료, 되돌리기 가능).
- `app/services/job_posting_service.py` — `create_posting`/`update_posting`/`_ensure_can_manage` 부서 선택사항 처리(빈 값=미지정, MANAGER 도 부서 미지정 시 역할만 검사).
- `app/services/job_extract_service.py` — `platform`(코드)+`platform_label` 반환, 도메인 매핑 확장(점핏/인크루트/커리어), `_clean_bullets`로 `- ` bullet·빈 줄 제거.
- `app/schemas/job_posting_schema.py` — `PostingCreateRequest.department_id` Optional.
- `app/templates/index.html` — JD 카드 항상 표시(hidden 제거), **단일 저장 버튼**(JD 카드 아래), 별도 [JD 저장] 버튼 제거. 캐시버스트 `v47→v48`.
- `app/static/app.js` — 통합 저장(`savePosting`이 공고→JD 순차 저장 `_savePostingJdIfPresent`), 부서 필수 검증 제거, openCreate/openEdit JD 항상 표시, extract confirm-후-덮어쓰기/플랫폼 코드 매핑.

## 부서/팀 필수 해제 위치
- 프론트 `savePosting`: `if (!deptId)` 검증 제거, 빈 부서면 `department_id:''` 전송.
- 백엔드 `create_posting`: 공고명만 필수, dept 빈 값 → `None` 저장. `_ensure_can_manage`: dept 없으면 역할(ADMIN/MANAGER)만 검사(VIEWER 403). `update_posting`: dept 빈 값으로 변경(미지정) 허용.
- DB: `department_id` NOT NULL 해제(미지정=NULL 저장). **임의 부서값 주입 안 함.** (resume_files.dept_id 는 여전히 NOT NULL → 부서 미지정 공고 업로드는 별도 TODO)

## JD 카드 항상 표시 / 저장 버튼 정리
- `postingJdSection`의 `hidden` 제거 → 공고 등록 팝업을 열면 **공고 기본 정보 + JD 상세가 동시에 표시**.
- 저장 버튼은 **하나**: 신규=`공고 등록`, 수정=`공고 수정`. 기존 "공고 저장/JD 등록/JD 저장" 다중 버튼 제거.
- 단일 클릭 저장 흐름: 공고 기본정보 저장(POST/PUT) → (JD 입력 내용 있으면) JD upsert(POST `/{id}/jd`, 기존 로직/Drive 폴더 생성 재사용). 공고는 성공·JD 실패 시 "공고는 저장되었으나 JD 저장 실패" 안내(기존 서비스가 각자 커밋하는 구조라 프론트 순차 호출).

## URL 자동 추출 (JD 포함) + 덮어쓰기
- 응답 `platform`(코드: SARAMIN/JOBKOREA/WANTED/JUMPIT/INCRUIT/CAREER) + `platform_label`. 프론트는 코드가 select option 에 있을 때만 선택(점핏/인크루트/커리어는 option 없으면 미선택).
- LLM 추출 결과의 `- ` bullet/빈 줄 제거 후 줄바꿈 문자열로 반환 → textarea 그대로 채움 → 저장 시 기존 `parseSkillsInput`(콤마/줄바꿈 split)로 **JSONB 배열** 저장(`required_skills`/`preferred_skills` 구조·점수 산식 불변).
- **덮어쓰기 정책**: 대상(공고명/플랫폼/주요업무/자격요건/우대사항) 중 값이 하나라도 있으면 **API 호출 전 confirm**("이미 입력된 공고/JD 내용이 있습니다. 가져온 공고 내용으로 덮어쓸까요?"). 취소→화면 값 유지(API 미호출). 확인→교체. 모두 비어 있으면 confirm 없이 진행. **부서/팀·상태는 절대 변경 안 함.** 빈 추출값은 기존 값 유지.

## URL 처리 흐름 / 권한 / SSRF (기존 유지)
- 권한 ADMIN/MANAGER(VIEWER 403) — URL 조회/LLM 호출 전. SSRF 방어(http(s) 외·localhost·127.0.0.1·0.0.0.0·169.254.169.254·사설/예약 IP 차단, 리다이렉트 hop 재검증). 디딤(주) 미확인 시 LLM 미호출 + company_verified=false. platform 은 URL 도메인 기준(LLM 아님). 새 라이브러리 미추가(stdlib + 기존 OpenAI 서비스).

## 테스트 방법
```
cd /mnt/d/workspace_ref/langgraph-gemini-resume-demo
uv run uvicorn app.main:app --reload     # http://localhost:8000
```
공고/JD 관리 → 공고 등록 → (JD 카드 처음부터 보임/버튼 "공고 등록" 하나) → 부서 미선택 저장 가능 → URL 입력 후 [공고 내용 가져오기](디딤 공고면 JD까지 채움/플랫폼 자동선택, 값 있으면 confirm) → 공고 등록 클릭(공고+JD 함께 저장).
```
SELECT id, posting_id, title, required_skills, preferred_skills FROM resume_ai.job_descriptions ORDER BY id DESC LIMIT 10;  -- (legacy) 현재 JD 는 resume_ai.job_posting_jds
SELECT id, posting_id, title, required_skills, preferred_skills FROM resume_ai.job_posting_jds ORDER BY id DESC LIMIT 10;
```

## 테스트 결과 (라이브 DB+Drive)
- `py_compile`/`node --check` 통과, 제거 식별자(jdSaveBtn/savePostingJd/_fillIfEmpty/EXTRACT_PLATFORM_VALUE) 잔존 0.
- DB: `department_id` nullable 적용 확인.
- 플랫폼 매핑: saramin→(SARAMIN,사람인), jumpit→(JUMPIT,점핏), unknown→(None,None). `_clean_bullets("- A\n- B\n\n  - C ")`→`"A\nB\nC"`.
- **E2E**: 부서 미지정 공고 등록(department_id=None) → JD 저장 시 `required_skills` JSONB **list** 저장 + 공고 Drive 폴더 생성 → list 에 JD 등록 완료 반영. (테스트 데이터/Drive 폴더 정리)
- (참고) 디딤 실제 공고 LLM 추출/화면 동작은 서버 기동 + 브라우저 v48 새로고침 후 사용자 확인 필요.

## 남은 이슈 / TODO (docs/TODO.md)
- 부서 미지정 공고의 이력서 업로드(resume_files.dept_id NOT NULL) 처리 정책.
- 공고+JD 저장의 단일 트랜잭션화(현재 순차 2-API). 플랫폼별 HTML/추출 정확도, JD 필드/DB 컬럼 정식 리팩토링 등.
