from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.google_drive_service import _log
from app.services.dept_config_service import (
    DeptConfigError,
    CACHE_FILE_REL,
    refresh_departments_from_drive,
    build_department_tree,
)
from app.services import department_db_service

# 화면(JD 등록 / 이력서 등록)의 부서 트리를 제공합니다.
# 부서 원천은 Google Drive config/dept_config.json 이지만, 화면 조회 기준은 **DB(resume_ai.departments)** 입니다.
# (로컬 cache JSON 은 더 이상 원천이 아니며 fallback/debug 용도)

router = APIRouter(prefix="/api/departments", tags=["Departments"])


def _error(step: str, message: str, hint: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status": "ERROR", "step": step, "error_message": message, "hint": hint},
    )


@router.get("/tree")
def get_departments_tree():
    """
    부서 트리를 **DB(resume_ai.departments)** 기준으로 반환합니다. (status=1 만)
    DB 에 부서가 없으면 동기화를 안내하는 에러를 반환합니다. (Drive API 는 호출하지 않음)
    """
    try:
        active = department_db_service.get_departments(active_only=True)
    except Exception as e:
        _log(f"[departments] DB 트리 조회 실패: {type(e).__name__}: {e}")
        return _error(
            "departments_db", f"부서 트리 조회 실패: {type(e).__name__}",
            "DB 연결 상태를 확인해주세요.", status_code=500,
        )
    if not active:
        return _error(
            "departments_db", "DB에 부서 정보가 없습니다.",
            "관리자 > Google Drive 동기화에서 부서 DB 동기화를 먼저 실행해주세요.",
        )
    return {
        "status": "OK",
        "source": "db",
        "dept_count": len(active),
        "active_dept_count": len(active),
        "tree": build_department_tree(active),
    }


@router.post("/sync-from-drive-config")
def sync_departments_from_drive_config():
    """
    Google Drive config/dept_config.json 을 읽어 정규화한 뒤 resume_ai.departments 에 upsert 합니다.
    (id 기준 insert/update, JSON 에서 사라진 부서는 삭제하지 않음. 로컬 cache 도 함께 갱신)
    """
    _log("===== /api/departments/sync-from-drive-config 시작 =====")
    # 1) Drive config 읽기 (+ cache 갱신)
    try:
        cache = refresh_departments_from_drive()
    except DeptConfigError as e:
        return _error(e.step, e.message, e.hint)
    except Exception as e:
        _log(f"[departments] Drive config 읽기 실패: {type(e).__name__}: {e}")
        return _error(
            "drive_config", f"{type(e).__name__}: {e}",
            "Google Drive 인증 및 config/dept_config.json 을 확인해주세요.", status_code=500,
        )

    # 2) DB upsert
    try:
        result = department_db_service.upsert_departments(cache["departments"])
    except Exception as e:
        _log(f"[departments] DB upsert 실패: {type(e).__name__}: {e}")
        return _error(
            "departments_db_upsert", f"{type(e).__name__}: {e}",
            "DB 연결 상태를 확인한 뒤 다시 시도해주세요.", status_code=500,
        )

    _log(f"===== /api/departments/sync-from-drive-config 완료 — {result} =====")
    return {
        "status": "OK",
        "source": "google_drive_config",
        "schema": "resume_ai",
        "table": "departments",
        "inserted": result["inserted"],
        "updated": result["updated"],
        "skipped": result["skipped"],
        "total": result["total"],
    }


@router.post("/refresh-cache")
def refresh_departments_cache():
    """
    (보조) Drive 의 config/dept_config.json 을 다시 읽어 로컬 부서 트리 캐시(JSON)만 갱신합니다.
    화면 트리 기준은 DB 이며, 이 캐시는 fallback/debug 용도입니다. (Drive 폴더는 미변경)
    """
    _log("===== /api/departments/refresh-cache 시작 =====")
    try:
        cache = refresh_departments_from_drive()
    except DeptConfigError as e:
        return _error(e.step, e.message, e.hint)
    except Exception as e:
        _log(f"[departments] 캐시 새로고침 실패: {type(e).__name__}: {e}")
        return _error(
            "refresh_cache", f"{type(e).__name__}: {e}",
            "Drive 인증 및 config/dept_config.json 을 확인하세요.", status_code=500,
        )

    _log("===== /api/departments/refresh-cache 완료 =====")
    return {
        "status": "OK",
        "source": cache["source"],
        "dept_count": cache["dept_count"],
        "active_dept_count": cache["active_dept_count"],
        "cache_file": CACHE_FILE_REL,
        "cached_at": cache["cached_at"],
    }
