from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine

# DB 초기화/점검 유틸입니다.
#
# 이번 단계 범위:
#  - DB 연결 테스트 (SELECT 1)
#  - 현재 DB / schema 조회
#  - resume_ai schema 가 없으면 생성 (테이블은 만들지 않음)
#
# 주의: 서버 시작 시 자동으로 create_all 하지 않습니다. (테이블 관리는 Alembic)


def ensure_schema() -> None:
    """resume_ai schema 가 없으면 생성합니다. (테이블 생성은 하지 않음)"""
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.DB_SCHEMA}"'))


def check_db_health() -> dict:
    """
    DB 연결을 점검하고 현재 DB/schema 정보를 반환합니다.
    schema 가 없으면 먼저 생성한 뒤 점검합니다. 실패 시 예외를 그대로 올립니다.
    """
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.DB_SCHEMA}"'))
        conn.execute(text("SELECT 1"))
        database = conn.execute(text("SELECT current_database()")).scalar()
        current_schema = conn.execute(text("SELECT current_schema()")).scalar()
    return {
        "database": database,
        "schema": settings.DB_SCHEMA,
        "current_schema": current_schema,
    }


def list_tables() -> list:
    """resume_ai 스키마의 테이블 목록을 반환합니다. (Alembic 내부 alembic_version 제외)"""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :schema AND table_type = 'BASE TABLE' "
                "AND table_name <> 'alembic_version' "
                "ORDER BY table_name"
            ),
            {"schema": settings.DB_SCHEMA},
        ).all()
    return [r[0] for r in rows]


# job_descriptions(legacy 부서 기준 JD)는 공고/JD 중심 전환으로 카운트 대상에서 제외했습니다.
_COUNT_TABLES = [
    "departments", "dept_drive_folders",
    "resume_upload_batches", "resume_files", "resume_analysis_results",
]


def table_counts() -> dict:
    """resume_ai 스키마의 주요 테이블 row 수를 반환합니다. (다른 스키마는 조회하지 않음)"""
    schema = settings.DB_SCHEMA
    counts = {}
    with engine.connect() as conn:
        for table in _COUNT_TABLES:
            # 테이블/스키마명은 코드 상수라 인젝션 위험 없음. resume_ai 로만 한정.
            counts[table] = conn.execute(
                text(f'SELECT count(*) FROM "{schema}"."{table}"')
            ).scalar()
    return counts


def list_table_comments() -> list:
    """
    resume_ai 스키마의 테이블/컬럼 comment 를 반환합니다.
    (DBeaver 외에 Swagger 에서도 comment 반영 여부를 확인하기 위함)
    """
    schema = settings.DB_SCHEMA
    with engine.connect() as conn:
        table_rows = conn.execute(
            text(
                "SELECT c.relname AS table_name, obj_description(c.oid) AS table_comment "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relkind = 'r' "
                "AND c.relname <> 'alembic_version' ORDER BY c.relname"
            ),
            {"schema": schema},
        ).all()
        col_rows = conn.execute(
            text(
                "SELECT c.relname AS table_name, a.attname AS column_name, "
                "format_type(a.atttypid, a.atttypmod) AS data_type, "
                "d.description AS column_comment "
                "FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_attribute a ON a.attrelid = c.oid "
                "LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = a.attnum "
                "WHERE n.nspname = :schema AND c.relkind = 'r' "
                "AND a.attnum > 0 AND NOT a.attisdropped "
                "ORDER BY c.relname, a.attnum"
            ),
            {"schema": schema},
        ).all()

    by_table = {}
    for table_name, table_comment in table_rows:
        by_table[table_name] = {
            "table_name": table_name,
            "table_comment": table_comment,
            "columns": [],
        }
    for table_name, column_name, data_type, column_comment in col_rows:
        if table_name in by_table:
            by_table[table_name]["columns"].append({
                "column_name": column_name,
                "data_type": data_type,
                "column_comment": column_comment,
            })
    return list(by_table.values())
