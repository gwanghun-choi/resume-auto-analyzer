"""create job_postings and job_posting_jds

Revision ID: 0003_create_job_postings_and_jds
Revises: 0002_create_users_table
Create Date: 2026-07-07

공고/JD 중심 구조 전환 테이블을 생성합니다.
- 원본: docs/sql/2026-06-12-posting-jd.sql 의 1) job_postings, 2) job_posting_jds 를 그대로 편입.
- department_id 는 이 시점에는 NOT NULL 로 생성하고, 0005 에서 nullable 로 완화합니다.
  (실제 운영 반영 순서와 동일 — docs/sql/2026-06-12-job-postings-dept-nullable.sql)
- created_by → users.id FK(ON DELETE SET NULL), posting_id → job_postings.id FK(ON DELETE CASCADE).
- 기존 DB(수동 SQL 반영됨)에서도 실패하지 않도록 IF NOT EXISTS 로 작성합니다(idempotent).
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_create_job_postings_and_jds"
down_revision: Union[str, None] = "0002_create_users_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ----- 1) 공고: job_postings -----
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_ai.job_postings (
            id                        bigserial PRIMARY KEY,
            title                     varchar(255) NOT NULL,
            department_id             varchar(50)  NOT NULL,
            platform_code             varchar(50)  NULL,
            platform_posting_url      text         NULL,
            status                    varchar(30)  NOT NULL DEFAULT 'OPEN',
            drive_folder_id           varchar(255) NULL,
            drive_inbox_folder_id     varchar(255) NULL,
            drive_completed_folder_id varchar(255) NULL,
            drive_failed_folder_id    varchar(255) NULL,
            created_by                bigint       NULL,
            created_at                timestamp    NOT NULL DEFAULT now(),
            updated_at                timestamp    NOT NULL DEFAULT now(),
            CONSTRAINT fk_job_postings_created_by
                FOREIGN KEY (created_by) REFERENCES resume_ai.users(id) ON DELETE SET NULL
        );
        """
    )
    op.execute(
        "COMMENT ON TABLE  resume_ai.job_postings IS "
        "'채용 공고. 외부 플랫폼 공고와 1:1 대응(현재). 부서는 권한 기준으로 유지.';"
    )
    op.execute(
        "COMMENT ON COLUMN resume_ai.job_postings.department_id IS "
        "'공고 소속 부서 id (departments.id). 권한 필터 기준.';"
    )
    op.execute(
        "COMMENT ON COLUMN resume_ai.job_postings.platform_code IS "
        "'외부 플랫폼 코드: SARAMIN/JOBKOREA/WANTED/ETC';"
    )
    op.execute(
        "COMMENT ON COLUMN resume_ai.job_postings.status IS '공고 상태: DRAFT/OPEN/CLOSED/INACTIVE';"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_job_postings_department_id ON resume_ai.job_postings (department_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_job_postings_status        ON resume_ai.job_postings (status);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_job_postings_platform_code ON resume_ai.job_postings (platform_code);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_job_postings_created_at    ON resume_ai.job_postings (created_at DESC);")

    # ----- 2) JD 상세: job_posting_jds (현재 1공고=1 active JD, 서비스에서 강제) -----
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_ai.job_posting_jds (
            id               bigserial PRIMARY KEY,
            posting_id       bigint       NOT NULL,
            title            varchar(255) NULL,
            required_skills  jsonb        NULL,
            preferred_skills jsonb        NULL,
            jd_content       text         NULL,
            is_active        boolean      NOT NULL DEFAULT true,
            created_by       bigint       NULL,
            created_at       timestamp    NOT NULL DEFAULT now(),
            updated_at       timestamp    NOT NULL DEFAULT now(),
            CONSTRAINT fk_job_posting_jds_posting
                FOREIGN KEY (posting_id) REFERENCES resume_ai.job_postings(id) ON DELETE CASCADE,
            CONSTRAINT fk_job_posting_jds_created_by
                FOREIGN KEY (created_by) REFERENCES resume_ai.users(id) ON DELETE SET NULL
        );
        """
    )
    op.execute(
        "COMMENT ON TABLE resume_ai.job_posting_jds IS "
        "'공고에 연결된 JD 상세. 현재 공고당 1개 active JD만 허용(서비스 레벨). "
        "DB unique 제약은 두지 않음(향후 1공고 N JD 확장 대비).';"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_job_posting_jds_posting_id ON resume_ai.job_posting_jds (posting_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_job_posting_jds_is_active  ON resume_ai.job_posting_jds (is_active);")


def downgrade() -> None:
    # 개발 환경 전용. FK 때문에 jds 를 먼저 제거합니다. (운영 DB 에서 실행 금지)
    op.execute("DROP TABLE IF EXISTS resume_ai.job_posting_jds;")
    op.execute("DROP TABLE IF EXISTS resume_ai.job_postings;")
