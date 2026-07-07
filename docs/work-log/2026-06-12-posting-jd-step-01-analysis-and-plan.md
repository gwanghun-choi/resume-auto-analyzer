# Step 01 — 현재 코드 파악 및 작업 계획

- **작업 일시**: 2026-06-12
- **작업 목표**: "부서/팀 중심" → "공고(job_posting)/JD 중심" 구조 전환을 위한 현재 구조 파악 및 단계 계획 수립.

## 전제/제약 (이번 세션)
- **DB가 내려가 있음** → 서버 실행·DB 쿼리·API 테스트·마이그레이션 실행 불가. 모든 DB 변경은 **SQL 파일로만** 작성하고 실행은 사용자에게 위임. 코드 검증은 정적(`py_compile`, `node --check`)으로만.
- **resume_ai 스키마만** 변경. 다른 스키마 절대 손대지 않음.
- MatchingService 산식, 추천 판정(80/60), threshold_score 재도입 금지, OpenAI 프롬프트/모델, Drive 인증/CA, users/departments/role 정책 변경 금지.
- 기존 동작(로그인/권한/부서 트리/Drive 동기화/다운로드/분석)은 **깨지지 않게 유지** — 새 구조는 **additive**(추가)로 얹고, posting_id 없는 기존 데이터는 방어 처리.

## 현재 구조 요약 (파악 결과)

### 모델 (`app/db/models/`)
- `Department`(departments, id=문자열 D00xxx), `User`(users, department_id), `JobDescription`(job_descriptions, dept_id 기반 JD), `DeptDriveFolder`(dept_drive_folders), `ResumeUploadBatch`(resume_upload_batches), `ResumeFile`(resume_files, **dept_id** String(100)), `ResumeAnalysisResult`(resume_analysis_results, PK=analysis_id, dept_id).
- **audit_logs 모델/코드 없음** (DB 테이블만 존재 가정).

### JD (현재 "부서별 JD")
- `app/api/jd_router.py` (`/api/jd/{dept_id}`, save→DB) + `app/api/jds_router.py` (`/api/jds` CRUD, 인가 적용). `jd_service.py`, `jd_db_service.py`. 화면: `view-jd`(부서 트리 + JD 폼).

### 업로드 / 현황 / 분석
- 업로드: `POST /api/resumes/upload-to-drive` (resumes_router, `resume_drive_upload_service`).
- 현황: `GET /api/resumes/status`, `/status/{id}`, `/status/export-excel`, `/{id}/download` (`resume_status_db_service`).
- 분석: `POST /api/resumes/analyze-pending|analyze-selected|analyze-all` (`resume_analysis_service`, `resume_analysis_db_service`, `matching_service`, `ai_agent_service`). 분석 대기 조회 `/pending-uploads`.
- 분석은 **부서 단위**: dept의 active JD + dept completed/failed Drive 폴더 기준.

### 권한 helper (`app/services/department_access_service.py`)
- `get_accessible_department_ids(db,user)`(ADMIN=None / MANAGER·VIEWER=subtree list), `ensure_department_access`, `ensure_can_run_analysis`(VIEWER 403), `ensure_can_upload_resume`, `ensure_can_manage_jd`, `ensure_can_download_resume`, `search_departments`, `build_department_path`, `department_exists`, recursive CTE(`_SUBTREE_CONTAINS_SQL`/`_SUBTREE_IDS_SQL`).
- `app/core/security.py`: `get_current_user`, `require_admin`.

### Drive
- `google_drive_service.py`(인증/CA/이동/다운로드 `download_bytes`), `dept_folder_sync_service.py`(부서 폴더 동기화), `dept_drive_folder_db_service.py`. 부서 inbox/completed/failed 폴더 구조.

### 프론트
- `templates/index.html` 단일 SPA + `static/app.js` + `static/style.css`. 좌측 메뉴 data-roles 권한 + canAccessSection 가드. 캐시버스트 현재 `v38`.

### 문서
- `README.md`, `docs/WORKFLOW.md`, `docs/TODO.md` 존재. `docs/work-log/` 신규 생성.

## 설계 결정 (공고/JD 중심)
- **부서/팀**: 권한·조직·필터 기준으로 **유지**.
- **공고(job_postings)**: 실제 채용 단위. department_id(권한), platform, status, Drive 폴더 id 보유.
- **JD(job_posting_jds)**: posting에 종속. 현재 1공고=1 active JD(서비스에서 강제, DB unique 안 검). required/preferred_skills + jd_content.
- **resume_files**: `posting_id`,`jd_id` 추가. `dept_id`는 유지(권한 호환). 업로드 시 posting.department_id를 resume_files.dept_id에 복사.
- **resume_analysis_results**: `posting_id`,`jd_id`,`jd_snapshot` 추가.
- posting_id 없는 기존 데이터 → 화면에서 공고명 "-"(미매핑) 방어.

## 단계 계획 (Step별 work-log)
- **Step 02 (DB)**: `docs/sql/` 에 신규 테이블/ALTER/인덱스 SQL 작성 (실행은 사용자). 모델 추가/컬럼 추가.
- **Step 03 (백엔드 공고/JD)**: 모델·스키마·서비스·라우터(`/api/job-postings`, `/{id}/jd`, `/search`) + 권한.
- **Step 04 (프론트 공고/JD 관리)**: 메뉴 "JD 관리"→"공고/JD 관리", 목록/등록 팝업/상세·JD 팝업, 부서 검색 재사용.
- **Step 05 (이력서 등록 전환)**: 공고/JD 선택 → posting_id/jd_id/dept_id 저장. (Drive 공고 폴더는 안전범위 내)
- **Step 06 (분석 전환)**: 공고/JD 기준 pending·분석(선택항목/선택공고/ADMIN 전체). posting→active JD.
- **Step 07 (현황 전환)**: 공고/JD 필터 + 공고명 컬럼/상세, 다운로드 유지, 미매핑 방어.
- **Step 08 (문서)**: README/WORKFLOW/TODO 갱신.
- **Step 09 (테스트/점검)**: 정적 검증 + 잔여 TODO.

## 이번 세션 범위 현실선 (정직한 고지)
DB 미가동·무테스트 단일 세션이라, **전 화면 풀 컷오버를 한 번에 무테스트로 강행하면 기존 동작이 깨질 위험**이 큼. 따라서:
- Step 02~04 + 08(문서) 를 **견고하게(additive, 정적검증)** 완료.
- Step 05~07 은 **백엔드 hook(posting_id/jd_id 저장·필터)을 backward-compatible 하게 추가**하고, 프론트 풀 전환의 잔여분은 work-log/TODO 에 명시.
- 기존 부서 기반 흐름은 fallback 으로 **그대로 유지**(삭제하지 않음). 죽은 코드 정리는 영향도 확인 후 보수적으로.

## 실패/주의사항
- DB 미가동으로 런타임 검증 불가 → 적용 후 사용자 측 테스트 필요.
- `resume_files`의 부서 컬럼명은 `department_id`가 아니라 **`dept_id`**(요구서 표기와 다름) — SQL/코드에서 실제 컬럼명 사용.
- 서버는 코드 반영 위해 **재시작** 필요(이전 작업들에서 stale 프로세스 404 이슈 반복됨).

## 다음 Step TODO
- Step 02: SQL 파일 작성(job_postings, job_posting_jds, resume_files/analysis_results ALTER, 인덱스) + 모델.
