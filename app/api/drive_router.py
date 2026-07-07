import os

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse

from app.services.google_drive_service import (
    GoogleDriveService,
    DriveConfigError,
    ROOT_FOLDER_NAME,
    TOKEN_PATH,
    _log,
)
from app.services.dept_folder_sync_service import (
    DeptFolderSyncService,
    read_sync_status,
)
from app.services.dept_config_service import (
    DeptConfigService,
    DeptConfigError,
    normalize_upload,
    validate_departments,
    save_cache,
)
from app.schemas.dept_config_schema import DeptConfigRequest
from app.services import department_db_service

# APIRouter 는 Spring 의 @RestController 와 비슷합니다.
# Google Drive 연결 확인 + 기본 폴더 생성/조회를 단계별로 수행하고,
# 실패 시 어느 단계(step)에서 깨졌는지 JSON 으로 명확히 돌려줍니다.

router = APIRouter(prefix="/api/drive", tags=["Drive"])


def _error_response(step: str, exc: Exception, hint: str) -> JSONResponse:
    """예외를 단계 정보가 담긴 JSON 으로 변환합니다. (FastAPI 기본 500 대신)"""
    return JSONResponse(
        status_code=500,
        content={
            "status": "ERROR",
            "step": step,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "cwd": os.getcwd(),
            "token_path": str(TOKEN_PATH.resolve()),
            "hint": hint,
        },
    )


def _step_error_response(step: str, message: str, hint: str, status_code: int = 500) -> JSONResponse:
    """단계(step)/메시지/힌트를 담은 에러 JSON 을 만듭니다. (예외 객체 메시지를 그대로 노출하지 않음)"""
    return JSONResponse(
        status_code=status_code,
        content={"status": "ERROR", "step": step, "error_message": message, "hint": hint},
    )


def _dept_config_error_response(e: DeptConfigError) -> JSONResponse:
    """부서 설정 JSON 입력 오류를 {status, step, error_message, hint} JSON 으로 변환합니다."""
    return JSONResponse(
        status_code=400,
        content={
            "status": "ERROR",
            "step": e.step,
            "error_message": e.message,
            "hint": e.hint,
        },
    )


@router.get("/test")
def test_drive():
    """
    Google Drive 연결을 확인하고 기본 폴더 구조를 생성/조회합니다.
    단계: oauth -> token_save -> drive_build -> folder_create
    각 단계에서 실패하면 step 을 구분해 원인/cwd/token_path/hint 를 JSON 으로 반환합니다.
    """
    _log("===== /api/drive/test 시작 =====")
    service = GoogleDriveService()

    # 1) OAuth 인증 (token.json 로드/갱신/최초 로그인)
    try:
        creds = service.authenticate()
    except DriveConfigError as e:
        _log(f"[oauth] 설정 오류: {e}")
        return _error_response(
            "oauth", e,
            "credentials.json 형식 문제일 수 있습니다. "
            "Desktop app(최상위 key 'installed') 형식인지 확인하세요.",
        )
    except Exception as e:
        _log(f"[oauth] 인증 실패: {type(e).__name__}: {e}")
        return _error_response(
            "oauth", e,
            "WSL 환경에서는 출력된 OAuth URL을 Windows 브라우저에 복사해서 인증해야 합니다. "
            "토큰 교환 단계 실패면 사내 프록시(SSL) 문제일 수 있습니다.",
        )

    # 2) token.json 저장 + 실제 생성 검증 (토큰을 새로 갱신/발급한 경우에만 저장)
    #    (OAuth 는 됐지만 token.json 이 안 생기는 경우를 별도로 잡음)
    try:
        if service.token_dirty:
            service.save_token(creds)
    except Exception as e:
        _log(f"[token_save] 저장 실패: {type(e).__name__}: {e}")
        return _error_response(
            "token_save", e,
            "OAuth 인증은 완료됐지만 token.json 저장/생성에 실패했습니다. "
            "프로젝트 루트 쓰기 권한과 token_path 를 확인하세요.",
        )

    # 3) Drive API 클라이언트 build
    try:
        service.build_drive(creds)
    except Exception as e:
        _log(f"[drive_build] build 실패: {type(e).__name__}: {e}")
        return _error_response(
            "drive_build", e,
            "Drive API 클라이언트 생성에 실패했습니다. 네트워크/SSL 설정을 확인하세요.",
        )

    # 4) 기본 폴더 생성/조회
    try:
        result = service.ensure_project_folders()
    except Exception as e:
        _log(f"[folder_create] 폴더 처리 실패: {type(e).__name__}: {e}")
        return _error_response(
            "folder_create", e,
            "Drive 폴더 생성/조회에 실패했습니다. "
            "토큰 권한(Scope)과 Drive API 사용 설정을 확인하세요.",
        )

    _log("===== /api/drive/test 성공 =====")
    return {
        "status": "OK",
        "root": {
            "name": ROOT_FOLDER_NAME,
            "folder_id": result["root_id"],
        },
        "folders": result["folders"],
    }


def _connect_drive(service: GoogleDriveService):
    """인증 → (필요 시) token.json 저장 → Drive build 까지 수행합니다. (실패 시 예외 전파)

    토큰을 새로 갱신/발급한 경우에만 저장합니다. (기존 유효 토큰이면 저장 생략 →
    저장 중 오해성 'token.json 생성 실패' 에러를 만들지 않음)
    """
    creds = service.authenticate()
    if service.token_dirty:
        service.save_token(creds)
    service.build_drive(creds)


@router.post("/sync-dept-folders")
def sync_dept_folders():
    """
    Drive 의 config/dept_config.json 을 기준으로 inbox/completed/failed 아래에
    부서 폴더를 동기화합니다. (평탄화 구조, status=1 만, 이름 중복 방지, 삭제/rename 안 함)

    더 이상 로컬 더미 JSON 을 기준으로 하지 않습니다. (로컬 더미는 최초 seed 용도)
    """
    _log("===== /api/drive/sync-dept-folders 시작 =====")
    service = GoogleDriveService()

    # 1) Drive 인증/빌드
    try:
        _connect_drive(service)
    except DriveConfigError as e:
        _log(f"[oauth] 설정 오류: {e}")
        return _error_response(
            "oauth", e,
            "credentials.json 형식(최상위 key 'installed')을 확인하세요.",
        )
    except Exception as e:
        _log(f"[oauth] 인증 실패: {type(e).__name__}: {e}")
        return _error_response(
            "oauth", e,
            "WSL 환경에서는 출력된 OAuth URL을 Windows 브라우저로 인증해야 합니다.",
        )

    # 2) 부서 목록은 DB(resume_ai.departments) 에서 조회합니다. (DB 가 기준)
    try:
        departments = department_db_service.get_departments(active_only=False)
    except Exception as e:
        _log(f"[departments_db] 조회 실패: {type(e).__name__}: {e}")
        return _error_response(
            "departments_db", e,
            "DB 연결 상태를 확인해주세요.",
        )
    if not departments:
        return JSONResponse(
            status_code=400,
            content={
                "status": "ERROR",
                "step": "departments_db",
                "error_message": "DB에 부서 정보가 없습니다.",
                "hint": "관리자 > Google Drive 동기화에서 'Drive config → DB 부서 동기화'를 먼저 실행해주세요.",
            },
        )

    # 3) 부서 폴더 동기화 (결과는 resume_ai.dept_drive_folders 에 저장)
    try:
        result = DeptFolderSyncService(service).sync(departments)
    except Exception as e:
        _log(f"[sync] 동기화 실패: {type(e).__name__}: {e}")
        return _error_response(
            "sync", e,
            "부서 폴더 동기화 중 오류가 발생했습니다. DB 부서/Drive 권한을 확인하세요.",
        )

    _log("===== /api/drive/sync-dept-folders 완료 =====")
    return result


@router.get("/sync-dept-folders/status")
def sync_dept_folders_status():
    """동기화 매핑 파일 상태를 조회합니다. (Drive 인증 불필요)"""
    return read_sync_status()


# ----- 부서 설정 JSON (config/dept_config.json) 관리 -----

@router.get("/dept-config")
def get_dept_config():
    """
    Drive 의 config/dept_config.json 을 조회합니다.
    파일이 없으면 로컬 더미 JSON 을 기준으로 최초 생성한 뒤 내려줍니다.
    departments 는 항상 배열 형태로 반환합니다.

    실패 시 인증 단계와 Drive 파일 처리 단계를 분리해 step 을 정확히 반환합니다.
    (인증이 정상인데 Drive 조회/다운로드/파싱에서 실패한 것을 'token 생성 실패' 로 보고하지 않습니다.)
    """
    _log("[drive-config] start load dept_config")
    service = GoogleDriveService()

    # 0) token.json 자체가 없으면 (진짜 미인증) 인증 안내만 반환합니다.
    if not TOKEN_PATH.exists():
        _log("[drive-config] error step = google_oauth_token_missing")
        return _step_error_response(
            "google_oauth_token_missing",
            "token.json이 없어 Google Drive 인증이 필요합니다.",
            "서버 터미널에 출력된 OAuth URL을 브라우저에서 열어 인증을 완료해주세요.",
        )

    # 1) 인증 (+ 토큰이 갱신/발급된 경우에만 저장)
    try:
        creds = service.authenticate()
        if service.token_dirty:
            service.save_token(creds)
        _log("[drive-config] auth success")
    except DriveConfigError as e:
        # authenticate() 가 던지는 DriveConfigError 는 주로 refresh 실패입니다.
        _log(f"[drive-config] error step = google_token_refresh_failed / type = {type(e).__name__}")
        return _step_error_response(
            "google_token_refresh_failed",
            "refresh_token으로 access token 갱신에 실패했습니다.",
            "Google 계정 권한이 제거되었거나 OAuth client/scopes가 변경되었을 수 있습니다.",
        )
    except Exception as e:
        _log(f"[drive-config] error step = google_oauth_failed / type = {type(e).__name__}")
        return _step_error_response(
            "google_oauth_failed",
            "Google Drive 인증 중 오류가 발생했습니다.",
            "credentials.json / token.json / OAuth scope를 확인해주세요.",
        )

    # 2) Drive service build
    try:
        service.build_drive(creds)
        _log("[drive-config] service build success")
    except Exception as e:
        _log(f"[drive-config] error step = google_drive_service_build_failed / type = {type(e).__name__}")
        return _step_error_response(
            "google_drive_service_build_failed",
            "Google Drive service 생성 중 오류가 발생했습니다.",
            "credentials.json, token.json, OAuth scope를 확인해주세요.",
        )

    # 3) config/dept_config.json 조회 → 다운로드 → JSON 파싱
    #    (폴더/파일/다운로드/파싱 실패는 DeptConfigService.read() 가 step 을 구분해 raise)
    try:
        result = DeptConfigService(service).read()
        _log("[drive-config] json parse success")
        # 불러올 때 화면 트리 캐시도 갱신합니다.
        save_cache(result["departments"], "google_drive_dept_config", result["file_id"])
        return result
    except DeptConfigError as e:
        _log(f"[drive-config] error step = {e.step} / type = DeptConfigError / message = {e.message}")
        return _dept_config_error_response(e)
    except Exception as e:
        _log(f"[drive-config] error step = dept_config_read / type = {type(e).__name__}")
        return _step_error_response(
            "dept_config_read",
            "dept_config.json 조회에 실패했습니다.",
            "Drive 파일 권한과 Google Drive API 접근 권한을 확인해주세요.",
        )


@router.post("/dept-config/normalize-upload")
async def normalize_upload_dept_config(file: UploadFile = File(...)):
    """
    업로드된 JSON 파일을 규칙 기반으로 정규화해서 반환합니다. (Drive 저장 안 함, 인증 불필요)
    임시 파일을 만들지 않고 메모리에서 처리합니다.
    """
    try:
        content = await file.read()
        return normalize_upload(content, file.filename)
    except DeptConfigError as e:
        return _dept_config_error_response(e)


@router.post("/dept-config/validate")
def validate_dept_config(body: DeptConfigRequest):
    """departments 구조 검증만 수행합니다. (Drive 저장 안 함, 인증 불필요)"""
    try:
        counts = validate_departments(body.departments)
    except DeptConfigError as e:
        return _dept_config_error_response(e)
    return {
        "status": "OK",
        "message": "검증 성공",
        "dept_count": counts["dept_count"],
        "active_dept_count": counts["active_dept_count"],
        "warnings": counts["warnings"],
    }


@router.put("/dept-config")
def put_dept_config(body: DeptConfigRequest):
    """
    departments 를 검증한 뒤 Drive 의 config/dept_config.json 을 '배열 JSON' 으로 저장합니다.
    검증 실패 시 Drive 파일을 덮어쓰지 않습니다.
    """
    service = GoogleDriveService()
    try:
        _connect_drive(service)
    except DriveConfigError as e:
        return _error_response("oauth", e, "credentials.json 형식(installed)을 확인하세요.")
    except Exception as e:
        return _error_response("oauth", e, "WSL 환경에서는 출력된 OAuth URL로 인증해야 합니다.")

    try:
        result = DeptConfigService(service).save(body.departments)
        # 저장 성공 시 화면 트리 캐시도 즉시 갱신합니다. (fallback/debug)
        save_cache(result["departments"], "google_drive_dept_config", result["file_id"])
        result["cache_updated"] = True
    except DeptConfigError as e:
        return _dept_config_error_response(e)  # 검증 실패 → Drive 미변경
    except Exception as e:
        return _error_response("dept_config_save", e, "dept_config.json 저장에 실패했습니다.")

    # Drive 저장 성공 후 DB(resume_ai.departments)도 동기화합니다.
    # DB 동기화가 실패해도 Drive 저장은 롤백하지 않고 PARTIAL_SUCCESS 로 알립니다.
    try:
        sync = department_db_service.upsert_departments(result["departments"])
    except Exception as e:
        _log(f"[dept_config_save] DB 동기화 실패: {type(e).__name__}: {e}")
        return {
            "status": "PARTIAL_SUCCESS",
            "drive_config_saved": True,
            "db_sync_status": "FAILED",
            "error_message": "Drive에는 저장됐지만 DB 동기화에 실패했습니다.",
            "hint": "DB 연결 상태를 확인한 뒤 부서 DB 동기화를 다시 실행해주세요.",
            "file_id": result.get("file_id"),
            "dept_count": result.get("dept_count"),
        }

    result["status"] = "OK"
    result["drive_config_saved"] = True
    result["db_sync_status"] = "OK"
    result["department_sync"] = {
        "inserted": sync["inserted"], "updated": sync["updated"], "skipped": sync["skipped"],
    }
    return result
