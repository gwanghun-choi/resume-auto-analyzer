"""make job_postings.department_id nullable

Revision ID: 0005_job_posting_dept_nullable
Revises: 0004_add_posting_jd_columns
Create Date: 2026-07-07

공고 등록/수정에서 부서/팀을 선택사항으로 변경(부서 미지정 공고 저장 허용).
- 원본: docs/sql/2026-06-12-job-postings-dept-nullable.sql.
- 이미 nullable 이면 DROP NOT NULL 은 무변화(idempotent).
- ORM(app/db/models/job_posting.py)의 department_id 도 nullable=True 로 맞춥니다(정합성).
- revision id 는 alembic_version.version_num(varchar(32)) 제한 때문에 32자 이내로 둡니다.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_job_posting_dept_nullable"
down_revision: Union[str, None] = "0004_add_posting_jd_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE resume_ai.job_postings ALTER COLUMN department_id DROP NOT NULL;")
    op.execute(
        "COMMENT ON COLUMN resume_ai.job_postings.department_id IS "
        "'공고 소속 부서 id (departments.id). 선택사항(미지정 가능). 권한 필터 기준.';"
    )


def downgrade() -> None:
    # 부서 필수로 복귀. department_id 가 NULL 인 데이터가 있으면 실패합니다(의도적 — 데이터 확인 필요).
    op.execute("ALTER TABLE resume_ai.job_postings ALTER COLUMN department_id SET NOT NULL;")
