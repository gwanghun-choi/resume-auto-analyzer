# Step 02 — DB SQL 작성 + ORM 모델 추가

- **작업 일시**: 2026-06-12
- **작업 목표**: 공고/JD 중심 전환을 위한 신규 테이블/컬럼/인덱스 SQL 작성(resume_ai 전용) + ORM 모델 반영. **DB 미가동이라 실행하지 않고 파일로만 작성.**

## 생성한 파일
- `docs/sql/2026-06-12-posting-jd.sql` — 실행용 SQL (idempotent, `IF NOT EXISTS`)
- `app/db/models/job_posting.py` — `JobPosting`(job_postings)
- `app/db/models/job_posting_jd.py` — `JobPostingJD`(job_posting_jds)

## 수정한 파일
- `app/db/models/resume_file.py` — `posting_id`, `jd_id` 컬럼 추가 (dept_id 유지)
- `app/db/models/resume_analysis_result.py` — `posting_id`, `jd_id`, `jd_snapshot` 추가 (dept_id 유지)
- `app/db/models/__init__.py` — `JobPosting`, `JobPostingJD` 등록

## 변경한 DB 객체 (SQL 파일 기준 — 실행 대기)
- **신규 테이블**
  - `resume_ai.job_postings` (id, title, **department_id**, platform_code, platform_posting_url, status='OPEN', drive_folder_id/inbox/completed/failed, created_by, created_at, updated_at). FK `created_by → users(id) ON DELETE SET NULL`.
  - `resume_ai.job_posting_jds` (id, **posting_id**, title, required_skills jsonb, preferred_skills jsonb, jd_content, is_active=true, created_by, created_at, updated_at). FK `posting_id → job_postings(id) ON DELETE CASCADE`, `created_by → users(id) ON DELETE SET NULL`.
- **컬럼 추가**
  - `resume_ai.resume_files`: `posting_id bigint NULL`, `jd_id bigint NULL` (기존 `dept_id` 유지)
  - `resume_ai.resume_analysis_results`: `posting_id bigint NULL`, `jd_id bigint NULL`, `jd_snapshot jsonb NULL`
- **인덱스**: job_postings(department_id/status/platform_code/created_at desc), job_posting_jds(posting_id/is_active), resume_files(posting_id/jd_id), resume_analysis_results(posting_id/jd_id/resume_file_id)

## 설계 메모
- `resume_files`의 부서 컬럼은 실제 **`dept_id`** (요구서의 `department_id` 표기와 다름). SQL/코드 모두 `dept_id` 사용.
- ORM에는 하드 FK를 두지 않음(기존 프로젝트 스타일: dept_id 등 문자열 참조). DB FK는 SQL에만 둠.
- 신규 모델의 `created_at/updated_at`은 **server_default=now()** 로 정의 → ORM insert 시 NULL 미전송(과거 users.updated_at NOT NULL 위반 이슈 회피).
- 1공고=1 active JD는 **DB unique 제약 없이 service에서 강제**(향후 N JD 확장 대비).

## 테스트한 내용
- `python -m py_compile` (신규/수정 모델 5개) 통과. (DB 미가동이라 실제 마이그레이션/쿼리 미실행)

## 실패/주의사항
- **이 SQL은 아직 적용되지 않았습니다.** 사용자가 DB 복구 후 `docs/sql/2026-06-12-posting-jd.sql` 을 resume_ai 대상으로 실행해야 합니다.
- 더미 데이터 INSERT는 파일 하단에 **주석 처리**로 제공(민감정보 없음).
- threshold_score 재도입 안 함, 다른 스키마 미변경.

## 적용해야 할 SQL (사용자 실행)
```bash
psql "<resume_ai 접속>" -f docs/sql/2026-06-12-posting-jd.sql
```

## 다음 Step TODO
- Step 03: 공고/JD 백엔드 — schema(`job_posting_schema`), service(`job_posting_service`), router(`/api/job-postings`, `/{id}/jd`, `/search`) + 권한(ADMIN 전체 / MANAGER subtree / VIEWER 조회만).
