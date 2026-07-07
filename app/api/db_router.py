from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db.health import check_db_health, list_tables, list_table_comments, table_counts


def _db_error(step: str, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "status": "ERROR",
            "step": step,
            "error_message": f"{type(exc).__name__}: {exc}",
            "hint": "DB 접속정보(.env) 및 마이그레이션(alembic upgrade head) 적용 여부를 확인해주세요.",
        },
    )

# APIRouter 는 Spring 의 @RestController 와 비슷합니다.
# DB 연결 상태를 점검하는 health check 엔드포인트입니다.
# (DB 가 죽어 있어도 서버는 죽지 않고 JSON 으로 에러를 돌려줍니다.)

router = APIRouter(prefix="/api/db", tags=["DB"])


@router.get("/health")
def db_health():
    """
    DB 연결을 확인하고 현재 database / schema 를 반환합니다.
    - SELECT 1 / current_database / current_schema 점검 + resume_ai schema 보장
    - 실패 시 {status, step, error_message, hint} JSON 으로 반환
    """
    try:
        info = check_db_health()
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "ERROR",
                "step": "db_connection",
                "error_message": f"{type(e).__name__}: {e}",
                "hint": "DB 접속정보(.env)를 확인해주세요.",
            },
        )

    return {
        "status": "OK",
        "database": info["database"],
        "schema": info["schema"],
        "message": "DB connection successful",
    }


@router.get("/tables")
def db_tables():
    """resume_ai 스키마의 테이블 목록을 반환합니다."""
    try:
        tables = list_tables()
    except Exception as e:
        return _db_error("db_query", e)
    return {"status": "OK", "schema": settings.DB_SCHEMA, "tables": tables}


@router.get("/table-comments")
def db_table_comments():
    """resume_ai 스키마의 테이블/컬럼 comment 를 반환합니다. (DBeaver 외 Swagger 확인용)"""
    try:
        tables = list_table_comments()
    except Exception as e:
        return _db_error("db_query", e)
    return {"status": "OK", "schema": settings.DB_SCHEMA, "tables": tables}


@router.get("/counts")
def db_counts():
    """resume_ai 스키마 주요 테이블의 row 수를 반환합니다. (다른 스키마는 조회하지 않음)"""
    try:
        counts = table_counts()
    except Exception as e:
        return _db_error("db_query", e)
    return {"status": "OK", "schema": settings.DB_SCHEMA, "counts": counts}
