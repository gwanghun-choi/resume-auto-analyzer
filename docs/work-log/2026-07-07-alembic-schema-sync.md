# [2026-07-07] Alembic 마이그레이션 정리 — 수동 SQL/외부 DDL 편입

## 1. 작업 배경 / 목적

DB 스키마 관리가 세 곳으로 분산되어 있었다.

- `alembic/versions/0001_create_resume_ai_tables.py` — 초기 6개 테이블(`departments`, `job_descriptions`, `dept_drive_folders`, `resume_upload_batches`, `resume_files`, `resume_analysis_results`).
- `docs/sql/2026-06-12-posting-jd.sql` — **수동 실행**하던 공고/JD 전환분(`job_postings`, `job_posting_jds` 생성 + `resume_files`/`resume_analysis_results` 컬럼 추가 + FK/인덱스).
- `docs/sql/2026-06-12-job-postings-dept-nullable.sql` — `job_postings.department_id` NOT NULL 해제.
- `users` — SQLAlchemy 모델(`app/db/models/user.py`)은 있으나 Alembic/`docs/sql` 어디에도 DDL 이 없이 "이미 생성되어 있다고 가정".

이 상태에서는 **빈 PostgreSQL DB 를 `alembic upgrade head` 한 번으로 재현할 수 없었다**(users/job_postings/job_posting_jds 누락, 수동 SQL 선행 필요).

**목표**: 빈 DB 에서 `alembic upgrade head` 한 번으로 현재 서비스가 필요한 테이블/컬럼/제약/인덱스가 모두 생성되도록 정리한다. 기존(수동 SQL 이 이미 적용된) DB 에서도 실패하지 않아야 한다.

## 2. 기존 문제

- 스키마 이원(삼원) 관리 → 신규 환경 구축 절차가 문서/구전에 의존.
- `users` DDL 부재 → 재현 불가.
- ORM ↔ DB drift: `JobPosting.department_id` 가 모델에선 `nullable=False` 인데 실제 DB(수동 SQL)는 nullable.

## 3. 변경 파일

### 추가 (Alembic revision, 모두 `down_revision` 으로 선형 체인)
- `alembic/versions/0002_create_users_table.py`
- `alembic/versions/0003_create_job_postings_and_jds.py`
- `alembic/versions/0004_add_posting_jd_columns.py`
- `alembic/versions/0005_job_posting_dept_nullable.py`

체인: `0001 → 0002 → 0003 → 0004 → 0005(head)`.

> revision id 는 `resume_ai.alembic_version.version_num` 컬럼이 `varchar(32)` 이므로 **32자 이내**로 지었다(초기 시도에서 44자 id 가 `StringDataRightTruncation` 로 실패 → 축약). 운영 DB 의 `alembic_version` 도 동일하게 32자이므로 이 제약을 반드시 지켜야 한다.

### 수정 (ORM 정합성 보정 — 스키마 정합 목적, 서비스 로직 불변)
- `app/db/models/job_posting.py` — `department_id` `nullable=False → True`.
- `app/db/models/resume_file.py` — `__table_args__` 에 `ix_resume_files_posting_id`, `ix_resume_files_jd_id` 인덱스 선언 추가.
- `app/db/models/resume_analysis_result.py` — `__table_args__` 에 `ix_analysis_results_posting_id`, `ix_analysis_results_jd_id` 인덱스 선언 추가(이름은 DB/수동 SQL 과 동일 표기).

### 문서
- `README.md` — "DB 초기화 / 마이그레이션 (Alembic)" 섹션 신규.
- `docs/WORKFLOW.md` — 초기 관리자 설정 플로우에 "DB 마이그레이션" 단계 추가.
- `docs/TODO.md` — 완료/남은 작업 섹션 추가.
- `docs/work-log/2026-07-07-alembic-schema-sync.md` — 본 문서.

## 4. 변경 내용 (핵심)

- `0002~0005` 는 `docs/sql/2026-06-12-*.sql` 의 **검증된 DDL 을 그대로 편입**했다(컬럼/타입/기본값/COMMENT/FK/인덱스 동일). `users` 만 모델(`app/db/models/user.py`)을 기준으로 신규 작성.
- 모든 DDL 을 **idempotent** 하게 작성: `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, `ALTER COLUMN ... DROP NOT NULL`(이미 nullable 이면 무변화). → 기존 DB 에서 재실행/부분적용 되어 있어도 실패하지 않는다.
- `docs/sql` 원본 스타일(이미 `IF NOT EXISTS` idempotent)을 그대로 따랐으므로 `alembic/env.py` 의 offline(`--sql`) 모드도 그대로 동작한다(인스펙터 의존 가드 미사용).
- FK: `job_postings.created_by → users(id)`(SET NULL), `job_posting_jds.posting_id → job_postings(id)`(CASCADE), `job_posting_jds.created_by → users(id)`(SET NULL) — 원본 SQL 과 동일. **이 때문에 `0002(users)` 가 `0003` 보다 먼저 와야 한다.**
- `department_id` 는 `0003` 에서 NOT NULL 로 생성 후 `0005` 에서 nullable 로 완화 — 실제 운영 반영 순서와 동일하게 재현.

## 5. 검증 방법 (일회용 Postgres 컨테이너, `postgres:16-alpine`)

접속 정보는 코드에 하드코딩하지 않고 `DATABASE_URL` 환경변수로만 주입해 검증했다(운영 `.env` 미변경).

1. **빈 DB → head**: 빈 DB 에서 `alembic upgrade head` → `0001~0005` 순서대로 성공, `alembic current` = `0005 (head)`.
   - `resume_ai` 테이블 9개 생성 확인(`users`, `departments`, `job_descriptions`, `dept_drive_folders`, `job_postings`, `job_posting_jds`, `resume_upload_batches`, `resume_files`, `resume_analysis_results`).
   - `users` 컬럼/nullable/기본값이 모델과 일치, `job_postings.department_id` = nullable(YES), FK 3개(SET NULL/CASCADE) 확인, resume 테이블의 `posting_id/jd_id/jd_snapshot` 확인.
2. **기존 DB → head (idempotency)**: `0001` 만 적용 + 외부 `users` DDL + 수동 SQL 2종 적용 후 `alembic_version` 을 `0001` 로 둔 상태에서 `alembic upgrade head` → **무충돌 성공**, `0005` 도달. 재실행 시 "nothing to do". `department_id` nullable 유지, FK 3개 유지.
3. **downgrade/upgrade 순환**: `0005 → 0001 → 0005` 왕복 성공. 단일 linear head 확인.
4. **앱 임포트/정합성**: `from app.db.base import Base` 정상, `alembic check` 결과는 아래 "주의사항"의 의도된 항목만 보고(구조적 신규 drift 없음).

## 6. 주의사항

- **`alembic check` / `--autogenerate` 사용 금지(권장하지 않음)**: 이 프로젝트는 손으로 마이그레이션을 작성하며, ORM 모델은 soft-reference 정책상 다음을 **일부러 선언하지 않는다**.
  - FK 3종(`fk_job_postings_created_by`, `fk_job_posting_jds_posting`, `fk_job_posting_jds_created_by`) — 모델은 `ForeignKey` 미사용(주석에 "FK 는 SQL 에 둔다"고 명시).
  - `ix_job_postings_created_at`(DESC), 중복 `ix_analysis_results_resume_file_id`.
  → `alembic check` 는 이들을 "제거해야 할 차이"로 보고하지만 **의도된 상태**다. autogenerate 로 리비전을 만들면 이 FK/인덱스 제거가 섞이므로, **새 리비전은 손으로 작성**할 것.
- COMMENT 문구는 모델 `comment=` 과 미세하게 다를 수 있으나(마이그레이션은 원본 SQL 문구 유지) 스키마 구조에는 영향 없음.
- revision id 32자 제한(§3 참고).

## 7. 기존 DB 적용 시 유의점

- **권장**: `uv run alembic upgrade head`. 모든 신규 리비전이 idempotent 라 이미 있는 객체는 건너뛰고 `alembic_version` 만 `0005` 로 전진한다(위 검증 2).
- **대안(무DDL)**: DB 스키마가 이미 `0005` 상태와 동일하다고 확신하면 `uv run alembic stamp head` 로 버전만 맞춘다.
  - ⚠️ `stamp` 는 실제 DDL 을 실행하지 않는다. **운영 DB 에는 스키마를 실제 확인한 뒤에만** 사용할 것. 스키마가 다르면 이후 drift 가 숨는다.
- 어느 방식이든 **파괴적 변경 없음**(DROP/데이터 삭제 없음). `.env` 실제 값은 변경하지 않았다.

## 8. 롤백 / 복구 참고

- 각 리비전에 `downgrade()` 제공(개발 전용). 순서: `0005(SET NOT NULL) → 0004(컬럼/인덱스 drop) → 0003(job_posting_jds→job_postings drop) → 0002(users drop)`.
  - **운영 DB 에서 downgrade 실행 금지**(테이블/컬럼 삭제 = 데이터 손실).
  - `0005` downgrade(`SET NOT NULL`)는 `department_id` 가 NULL 인 행이 있으면 실패한다(의도적 — 데이터 확인 필요).
- 잘못 전진한 경우: `alembic downgrade <직전 revision>` 또는 특정 리비전 지정. 운영에서는 백업(pg_dump) 후 진행 권장.
- 원본 수동 SQL(`docs/sql/2026-06-12-*.sql`)은 삭제하지 않고 참고용으로 유지한다.
