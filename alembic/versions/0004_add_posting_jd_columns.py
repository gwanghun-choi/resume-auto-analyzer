"""add posting_id/jd_id(/jd_snapshot) columns to resume tables

Revision ID: 0004_add_posting_jd_columns
Revises: 0003_create_job_postings_and_jds
Create Date: 2026-07-07

공고/JD 중심 전환에 따라 resume_files / resume_analysis_results 에 공고/JD 참조 컬럼을 추가합니다.
- 원본: docs/sql/2026-06-12-posting-jd.sql 의 3) resume_files, 4) resume_analysis_results.
- posting_id / jd_id 는 nullable (기존 데이터는 NULL=미매핑). 하드 FK 는 두지 않고 인덱스만 둡니다
  (dept_id 참조와 동일한 soft reference 정책).
- 기존 DB(수동 SQL 반영됨)에서도 실패하지 않도록 ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS
  로 작성합니다(idempotent).
- revision id 는 alembic_version.version_num(varchar(32)) 제한 때문에 32자 이내로 둡니다.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_add_posting_jd_columns"
down_revision: Union[str, None] = "0003_create_job_postings_and_jds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ----- 3) resume_files: posting_id / jd_id 추가 (dept_id 는 유지) -----
    op.execute("ALTER TABLE resume_ai.resume_files ADD COLUMN IF NOT EXISTS posting_id bigint NULL;")
    op.execute("ALTER TABLE resume_ai.resume_files ADD COLUMN IF NOT EXISTS jd_id      bigint NULL;")
    op.execute(
        "COMMENT ON COLUMN resume_ai.resume_files.posting_id IS "
        "'업로드된 공고 id (job_postings.id). 기존 데이터는 NULL=미매핑.';"
    )
    op.execute(
        "COMMENT ON COLUMN resume_ai.resume_files.jd_id IS "
        "'업로드 시점 공고의 active JD id (job_posting_jds.id).';"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_resume_files_posting_id ON resume_ai.resume_files (posting_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_resume_files_jd_id      ON resume_ai.resume_files (jd_id);")

    # ----- 4) resume_analysis_results: posting_id / jd_id / jd_snapshot 추가 -----
    op.execute("ALTER TABLE resume_ai.resume_analysis_results ADD COLUMN IF NOT EXISTS posting_id  bigint NULL;")
    op.execute("ALTER TABLE resume_ai.resume_analysis_results ADD COLUMN IF NOT EXISTS jd_id       bigint NULL;")
    op.execute("ALTER TABLE resume_ai.resume_analysis_results ADD COLUMN IF NOT EXISTS jd_snapshot jsonb  NULL;")
    op.execute(
        "COMMENT ON COLUMN resume_ai.resume_analysis_results.posting_id IS '분석 기준 공고 id.';"
    )
    op.execute(
        "COMMENT ON COLUMN resume_ai.resume_analysis_results.jd_id IS '분석 기준 JD id.';"
    )
    op.execute(
        "COMMENT ON COLUMN resume_ai.resume_analysis_results.jd_snapshot IS "
        "'분석 당시 JD 스냅샷(title/required_skills/preferred_skills/jd_content).';"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analysis_results_posting_id "
        "ON resume_ai.resume_analysis_results (posting_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analysis_results_jd_id "
        "ON resume_ai.resume_analysis_results (jd_id);"
    )
    # 0001 에 이미 ix_resume_analysis_results_resume_file_id 가 있으나, 수동 SQL 이 별도 이름으로
    # resume_file_id 인덱스를 추가했으므로 기존 운영 DB 와 동일하게 재현합니다(중복이지만 IF NOT EXISTS).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analysis_results_resume_file_id "
        "ON resume_ai.resume_analysis_results (resume_file_id);"
    )


def downgrade() -> None:
    # 개발 환경 전용. 컬럼 삭제 시 해당 컬럼 인덱스도 함께 제거됩니다. (운영 DB 에서 실행 금지)
    op.execute("DROP INDEX IF EXISTS resume_ai.ix_analysis_results_resume_file_id;")
    op.execute("ALTER TABLE resume_ai.resume_analysis_results DROP COLUMN IF EXISTS jd_snapshot;")
    op.execute("ALTER TABLE resume_ai.resume_analysis_results DROP COLUMN IF EXISTS jd_id;")
    op.execute("ALTER TABLE resume_ai.resume_analysis_results DROP COLUMN IF EXISTS posting_id;")
    op.execute("ALTER TABLE resume_ai.resume_files DROP COLUMN IF EXISTS jd_id;")
    op.execute("ALTER TABLE resume_ai.resume_files DROP COLUMN IF EXISTS posting_id;")
