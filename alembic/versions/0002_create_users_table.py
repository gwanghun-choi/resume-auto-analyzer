"""create users table

Revision ID: 0002_create_users_table
Revises: 0001_create_resume_ai_tables
Create Date: 2026-07-07

resume_ai.users 테이블을 생성합니다. (기존에는 Alembic/docs/sql 에 DDL 이 없이
"이미 생성되어 있다고 가정" 하던 테이블을 마이그레이션으로 편입)

- 컬럼/타입/nullable 은 app/db/models/user.py(User 모델) 기준입니다.
- job_postings/job_posting_jds.created_by 가 users.id 를 FK 로 참조하므로,
  반드시 0003(공고/JD) 보다 먼저 생성되어야 합니다.
- 이미 users 가 존재하는 기존 DB 에서도 실패하지 않도록 IF NOT EXISTS 로 작성합니다(idempotent).
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_create_users_table"
down_revision: Union[str, None] = "0001_create_resume_ai_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_ai.users (
            id            bigserial PRIMARY KEY,
            login_id      varchar(100) NOT NULL,
            email         varchar(255) NOT NULL,
            name          varchar(100) NOT NULL,
            password_hash text         NOT NULL,
            role_code     varchar(30)  NOT NULL,
            department_id varchar(50)  NULL,
            is_active     boolean      NOT NULL DEFAULT true,
            last_login_at timestamp    NULL,
            created_at    timestamp    NOT NULL DEFAULT now(),
            updated_at    timestamp    NULL,
            CONSTRAINT uq_users_login_id UNIQUE (login_id),
            CONSTRAINT uq_users_email    UNIQUE (email)
        );
        """
    )
    op.execute("COMMENT ON TABLE  resume_ai.users IS '로그인 사용자 계정 테이블.';")
    op.execute("COMMENT ON COLUMN resume_ai.users.id IS '사용자 PK (BIGSERIAL)';")
    op.execute("COMMENT ON COLUMN resume_ai.users.login_id IS '로그인 ID';")
    op.execute("COMMENT ON COLUMN resume_ai.users.email IS '이메일';")
    op.execute("COMMENT ON COLUMN resume_ai.users.name IS '사용자 표시 이름';")
    op.execute(
        "COMMENT ON COLUMN resume_ai.users.password_hash IS "
        "'비밀번호. 현재 단계는 평문 비교(운영 전 해시 검증으로 교체 예정)';"
    )
    op.execute("COMMENT ON COLUMN resume_ai.users.role_code IS '역할 코드 (ADMIN/MANAGER/VIEWER)';")
    op.execute("COMMENT ON COLUMN resume_ai.users.department_id IS '소속 부서 ID. departments.id(문자열) 참조';")
    op.execute("COMMENT ON COLUMN resume_ai.users.is_active IS '활성 여부';")
    op.execute("COMMENT ON COLUMN resume_ai.users.last_login_at IS '마지막 로그인 시각';")

    op.execute("CREATE INDEX IF NOT EXISTS ix_users_login_id ON resume_ai.users (login_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_email    ON resume_ai.users (email);")


def downgrade() -> None:
    # 개발 환경 전용. (운영 DB 에서 실행 금지)
    op.execute("DROP TABLE IF EXISTS resume_ai.users;")
