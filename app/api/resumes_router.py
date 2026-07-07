import io
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.services.google_drive_service import GoogleDriveService, DriveConfigError, TOKEN_PATH, _log
from app.services.resume_drive_upload_service import (
    ResumeDriveUploadService,
    ResumeUploadError,
)
from app.services import resume_upload_db_service
from app.services import resume_status_db_service
from app.services import resume_analysis_db_service
from app.services import department_access_service
from app.services import job_posting_service
from app.services.department_access_service import (
    ensure_can_upload_resume,
    ensure_department_access,
    ensure_can_run_analysis,
    ensure_can_download_resume,
)
from app.services.resume_status_excel_service import build_status_excel
from app.services.resume_analysis_service import (
    ResumeAnalysisService,
    ResumeAnalysisError,
)
from app.tasks.resume_analysis_tasks import analyze_resume_posting_task
from app.core.celery_app import RESUME_ANALYSIS_QUEUE
from app.schemas.resume_analyze_schema import (
    AnalyzePendingRequest, AnalyzeSelectedRequest, AnalyzePostingRequest,
)
from app.core.security import get_current_user
from app.db.session import get_db
from app.db.models.user import User

# 이력서 등록 화면에서 올린 파일을 Google Drive 부서 inbox 폴더에 저장합니다.
# (AI 분석/이동은 하지 않습니다. 저장 + 기록까지만.)

router = APIRouter(prefix="/api/resumes", tags=["Resumes"])


def _error(step: str, message: str, hint: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status": "ERROR", "step": step, "error_message": message, "hint": hint},
    )


@router.post("/upload-to-drive")
async def upload_to_drive(dept_id: str = Form(""), posting_id: str = Form(""),
                          files: list[UploadFile] = File(...),
                          current_user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """
    공고(posting_id) 또는 부서(dept_id, legacy)의 inbox/{upload_id} 폴더에 이력서 파일을 업로드합니다.

    공고 기준(posting_id):
      - 권한: ADMIN 전체 / MANAGER 본인 부서+하위 / VIEWER 403
      - JD 가 등록된 공고만 업로드 가능, 공고 Drive inbox 폴더로 업로드
      - resume_files 에 posting_id/jd_id 저장, dept_id 는 공고 부서로 복사 저장
    인증 단계와 실제 업로드 처리 단계를 분리해 step 을 정확히 반환합니다.
    """
    _log("[resume-upload] start")

    # 0) 공고 기준 업로드: 공고/JD/Drive 폴더/권한을 먼저 확정합니다.
    upload_kwargs = {}
    posting_id = (posting_id or "").strip()
    if posting_id:
        try:
            pid = int(posting_id)
        except ValueError:
            return _error("posting_required", "공고 식별자가 올바르지 않습니다.", "공고를 다시 선택해주세요.")
        posting = job_posting_service.get_posting_entity(db, pid)
        # 권한(VIEWER/권한 밖 부서 403) — 파일 읽기/Drive 전에 차단
        job_posting_service.ensure_can_manage_posting(db, current_user, posting)
        jd = job_posting_service.get_active_jd_entity(db, pid)
        if jd is None:
            return _error("posting_jd_required", "JD가 등록된 공고에만 이력서를 업로드할 수 있습니다.",
                          "공고 상세에서 JD를 먼저 등록해주세요.")
        if not posting.drive_inbox_folder_id:
            return _error("posting_drive_folder_missing", "공고의 Google Drive inbox 폴더가 없습니다.",
                          "공고를 다시 등록하거나 관리자에게 문의해주세요.")
        dept_id = posting.department_id  # resume_files.dept_id 에 공고 부서 복사
        _node, _ = department_access_service.get_department_node_map(db)
        dept_name = _node[dept_id][0] if dept_id in _node else ""
        upload_kwargs = {
            "inbox_entry": {"inbox_folder_id": posting.drive_inbox_folder_id,
                            "dept_name": dept_name,
                            "folder_name": f"JP{pid:06d}_{posting.title}"},
            "posting_id": pid, "jd_id": jd.id,
        }
        _log(f"[resume-upload] posting_id = {pid}, dept_id = {dept_id}, jd_id = {jd.id}")
    else:
        # 1) (legacy) 선택 부서 확인
        if not (dept_id or "").strip():
            _log("[resume-upload] error step = dept_required")
            return _error("dept_required", "업로드 대상 공고가 선택되지 않았습니다.",
                          "공고/JD 목록에서 업로드할 공고를 선택해주세요.")
        _log(f"[resume-upload] dept_id = {dept_id}")
        # 1-1) 업로드 권한 검사 — 반드시 파일 읽기/Drive 업로드/DB 저장 전에 수행
        ensure_can_upload_resume(db, current_user, dept_id)

    # 2) 업로드 파일을 메모리로 읽어둡니다. (zip 해제/Drive 업로드에 사용)
    items = []
    for uf in files:
        items.append({
            "filename": uf.filename,
            "content_type": uf.content_type,
            "data": await uf.read(),
        })
    if not items or all(not it.get("data") for it in items):
        _log("[resume-upload] error step = upload_file_required")
        return _error("upload_file_required", "업로드할 파일이 없습니다.",
                      "이력서 파일을 선택한 뒤 다시 시도해주세요.")
    _log(f"[resume-upload] file_count = {len(items)}")

    # 3) 인증 (+ 토큰이 갱신/발급된 경우에만 저장). token 자체가 없으면 인증 안내만 반환.
    service = GoogleDriveService()
    if not TOKEN_PATH.exists():
        _log("[resume-upload] error step = google_oauth_token_missing")
        return _error("google_oauth_token_missing",
                      "token.json이 없어 Google Drive 인증이 필요합니다.",
                      "서버 터미널에 출력된 OAuth URL을 브라우저에서 열어 인증을 완료해주세요.")
    try:
        creds = service.authenticate()
        if service.token_dirty:
            service.save_token(creds)
        _log("[resume-upload] auth success")
    except DriveConfigError as e:
        _log(f"[resume-upload] error step = google_token_refresh_failed / type = {type(e).__name__}")
        return _error("google_token_refresh_failed",
                      "refresh_token으로 access token 갱신에 실패했습니다.",
                      "Google 계정 권한이 제거되었거나 OAuth client/scopes가 변경되었을 수 있습니다.")
    except Exception as e:
        _log(f"[resume-upload] error step = google_oauth_failed / type = {type(e).__name__}")
        return _error("google_oauth_failed", "Google Drive 인증 중 오류가 발생했습니다.",
                      "credentials.json / token.json / OAuth scope를 확인해주세요.", 500)

    # 4) Drive service build
    try:
        service.build_drive(creds)
        _log("[resume-upload] drive service build success")
    except Exception as e:
        _log(f"[resume-upload] error step = google_drive_service_build_failed / type = {type(e).__name__}")
        return _error("google_drive_service_build_failed",
                      "Google Drive service 생성 중 오류가 발생했습니다.",
                      "credentials.json, token.json, OAuth scope를 확인해주세요.", 500)

    # 5) 업로드 처리 (폴더 매핑/생성/업로드/DB 저장 실패는 ResumeUploadError 가 step 을 구분)
    try:
        result = ResumeDriveUploadService(service).upload(dept_id, items, **upload_kwargs)
    except ResumeUploadError as e:
        _log(f"[resume-upload] error step = {e.step} / type = ResumeUploadError / message = {e.message}")
        return _error(e.step, e.message, e.hint)
    except Exception as e:
        _log(f"[resume-upload] error step = drive_file_upload_failed / type = {type(e).__name__}")
        return _error("drive_file_upload_failed",
                      "Google Drive 파일 업로드 중 오류가 발생했습니다.",
                      "파일 형식, 파일 크기, Drive 권한을 확인해주세요.", 500)

    _log("[resume-upload] done")
    return result


@router.get("/pending-uploads")
def pending_uploads(dept_id: str = "",
                    current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """
    분석 대기 파일 목록을 **DB(resume_ai)** 기준으로 반환합니다. (Drive 인증 불필요)
    - dept_id 있음: 해당 부서 (권한 밖이면 403)
    - dept_id 없음('전체 부서'): 로그인 사용자 권한 범위 전체
      (ADMIN=전사 전체 / MANAGER·VIEWER=본인 부서+하위 — 백엔드에서 권한 필터링)
    """
    if not dept_id:
        # 전체 부서: 권한 범위 부서 id 목록(ADMIN=None=전체, MANAGER/VIEWER=리스트)으로 백엔드 필터링
        allowed_ids = department_access_service.get_accessible_department_ids(db, current_user)
        try:
            return resume_upload_db_service.get_pending_uploads_for_scope(allowed_ids)
        except Exception as e:
            _log(f"[pending-uploads] (scope=all) DB 조회 실패: {type(e).__name__}: {e}")
            return _error(
                "pending_uploads_db_query", f"{type(e).__name__}: {e}",
                "분석 대기 파일 DB 조회 중 오류가 발생했습니다.", 500,
            )
    # 특정 부서: ADMIN 전체 / MANAGER·VIEWER 본인 하위만 (권한 밖 dept_id 는 403)
    ensure_department_access(db, current_user, dept_id)
    try:
        return resume_upload_db_service.get_pending_uploads_from_db(dept_id)
    except Exception as e:
        _log(f"[pending-uploads] DB 조회 실패: {type(e).__name__}: {e}")
        return _error(
            "pending_uploads_db_query", f"{type(e).__name__}: {e}",
            "분석 대기 파일 DB 조회 중 오류가 발생했습니다.", 500,
        )


@router.get("/debug-pending")
def debug_pending(dept_id: str = "",
                  current_user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """디버그용: 부서의 batch/파일 저장 현황과 pending 파일 수를 빠르게 확인합니다. (DB, resume_ai, 권한 부서만)"""
    if not dept_id:
        return _error("request", "dept_id가 전달되지 않았습니다.", "부서/팀을 먼저 선택해주세요.")
    ensure_department_access(db, current_user, dept_id)
    try:
        return resume_upload_db_service.get_pending_debug(dept_id)
    except Exception as e:
        _log(f"[debug-pending] DB 조회 실패: {type(e).__name__}: {e}")
        return _error(
            "pending_uploads_db_query", f"{type(e).__name__}: {e}",
            "분석 대기 파일 DB 조회 중 오류가 발생했습니다.", 500,
        )


# ===== 이력서 현황 조회 (DB resume_ai 기준 · 읽기 전용) =====
# 주의: 경로 매칭 순서상 /status/export-excel 을 /status/{resume_file_id} 보다 먼저 선언합니다.


def _resolve_allowed_dept_ids(current_user, db, requested_dept_id):
    """
    로그인 사용자의 권한 부서 id 목록을 계산하고, 명시적으로 요청한 dept_id 가
    권한 밖이면 403 으로 차단합니다. (목록/엑셀 공용)
    반환: allowed_dept_ids (ADMIN=None 전체 허용, MANAGER/VIEWER=부서 id 리스트)
    """
    allowed_ids = department_access_service.get_accessible_department_ids(db, current_user)
    if allowed_ids is not None and requested_dept_id and requested_dept_id not in allowed_ids:
        raise HTTPException(status_code=403, detail="해당 부서에 대한 권한이 없습니다.")
    return allowed_ids


@router.get("/status")
def resume_status_list(dept_id: str = "", analysis_status: str = "", recommendation: str = "",
                       keyword: str = "", date_from: str = "", date_to: str = "",
                       posting_id: str = "", posting_keyword: str = "",
                       page: int = 1, size: int = 20,
                       current_user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """이력서 파일 목록을 DB(resume_ai) 기준으로 조회합니다. (검색/필터/페이징 + 권한 부서/공고 필터)"""
    # 권한 계산 + 권한 밖 dept_id 요청 차단 (HTTPException 은 try 밖에서 전파)
    allowed_ids = _resolve_allowed_dept_ids(current_user, db, dept_id or None)
    try:
        return resume_status_db_service.get_status_list(
            dept_id=dept_id or None, analysis_status=analysis_status or None,
            recommendation=recommendation or None, keyword=keyword or None,
            date_from=date_from or None, date_to=date_to or None, page=page, size=size,
            allowed_dept_ids=allowed_ids,
            posting_id=(int(posting_id) if posting_id else None),
            posting_keyword=posting_keyword or None,
        )
    except Exception as e:
        _log(f"[resume-status] 목록 DB 조회 실패: {type(e).__name__}: {e}")
        return _error(
            "resume_status_query", f"{type(e).__name__}: {e}",
            "이력서 현황 조회 중 오류가 발생했습니다.", 500,
        )


@router.get("/status/export-excel")
def resume_status_export_excel(dept_id: str = "", analysis_status: str = "", recommendation: str = "",
                               keyword: str = "", date_from: str = "", date_to: str = "",
                               posting_id: str = "", posting_keyword: str = "",
                               current_user: User = Depends(get_current_user),
                               db: Session = Depends(get_db)):
    """현재 검색/필터 조건의 이력서 현황 전체를 Excel(.xlsx)로 다운로드합니다. (페이징 없음 + 권한 부서/공고 필터)"""
    # 화면 조회와 동일한 권한 필터를 적용합니다. (Excel 로 권한 밖 개인정보가 새지 않도록)
    allowed_ids = _resolve_allowed_dept_ids(current_user, db, dept_id or None)
    try:
        rows = resume_status_db_service.get_status_export_rows(
            dept_id=dept_id or None, analysis_status=analysis_status or None,
            recommendation=recommendation or None, keyword=keyword or None,
            date_from=date_from or None, date_to=date_to or None,
            allowed_dept_ids=allowed_ids,
            posting_id=(int(posting_id) if posting_id else None),
            posting_keyword=posting_keyword or None,
        )
        bio = build_status_excel(rows)
        filename = f"resume_status_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return StreamingResponse(
            bio,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        _log(f"[resume-status] Excel 생성 실패: {type(e).__name__}: {e}")
        return _error(
            "resume_status_excel", f"{type(e).__name__}: {e}",
            "이력서 현황 Excel 생성 중 오류가 발생했습니다.", 500,
        )


@router.get("/status/{resume_file_id}")
def resume_status_detail(resume_file_id: int,
                         current_user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """이력서 파일 1건의 상세 정보 + 업로드 회차 + 최신 분석 결과를 조회합니다. (권한 부서만)"""
    # 권한 부서 계산 (ADMIN=None). HTTPException(400/404) 은 try 밖에서 전파.
    allowed_ids = department_access_service.get_accessible_department_ids(db, current_user)
    try:
        detail = resume_status_db_service.get_status_detail(resume_file_id)
    except Exception as e:
        _log(f"[resume-status] 상세 DB 조회 실패: {type(e).__name__}: {e}")
        return _error(
            "resume_status_query", f"{type(e).__name__}: {e}",
            "이력서 현황 상세 조회 중 오류가 발생했습니다.", 500,
        )
    if detail is None:
        return _error(
            "resume_status_not_found", f"resume_file_id={resume_file_id} 에 해당하는 이력서가 없습니다.",
            "목록에서 다시 선택해주세요.", 404,
        )
    # 권한 밖 부서의 이력서 상세는 차단 (개인정보 보호)
    if allowed_ids is not None and detail["resume_file"]["dept_id"] not in allowed_ids:
        raise HTTPException(status_code=403, detail="해당 부서에 대한 권한이 없습니다.")
    return detail


@router.get("/{resume_file_id}/download")
def download_resume_file(resume_file_id: int,
                         current_user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """
    이력서 원본 파일(Google Drive 저장본)을 다운로드합니다.
    - 로그인 필수(401), 부서 권한 검증(ADMIN 전체 / MANAGER 본인 하위 / VIEWER 403)
    - 존재하지 않는 파일 404, drive_file_id 없으면 404
    - DB 의 원본 파일명으로 attachment 반환 (한글 파일명은 UTF-8 filename*)
    """
    meta = resume_status_db_service.get_file_for_download(resume_file_id)
    if not meta:
        raise HTTPException(status_code=404, detail="이력서를 찾을 수 없습니다.")

    # 권한: 권한 밖 부서 / VIEWER 는 403 (프론트 숨김과 별개로 백엔드에서 반드시 검증)
    ensure_can_download_resume(db, current_user, meta["dept_id"])

    drive_file_id = meta.get("drive_file_id")
    if not drive_file_id:
        raise HTTPException(status_code=404, detail="다운로드할 원본 파일을 찾을 수 없습니다.")

    # Google Drive 인증/build (기존 공통 헬퍼 재사용 — 회사망 SSL/ca_certs 설정 포함)
    service, drive_err = _build_drive_service_or_error()
    if drive_err is not None:
        return drive_err
    try:
        content = service.download_bytes(drive_file_id)
    except Exception as e:
        _log(f"[resume-download] Drive 다운로드 실패: file_id={resume_file_id}: {type(e).__name__}: {e}")
        return _error("resume_download_failed", "파일 다운로드 중 오류가 발생했습니다.",
                      "잠시 후 다시 시도하거나 관리자에게 문의해주세요.", 500)

    filename = meta.get("original_file_name") or meta.get("stored_file_name") or f"resume_{resume_file_id}"
    # 비ASCII(한글 등) 파일명: RFC 5987 filename*=UTF-8'' 인코딩으로 깨짐 방지
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    media_type = meta.get("content_type") or "application/octet-stream"
    return StreamingResponse(io.BytesIO(content), media_type=media_type,
                             headers={"Content-Disposition": disposition})


@router.post("/analyze-pending")
def analyze_pending(body: AnalyzePendingRequest,
                    current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """
    LEGACY ENDPOINT — 부서(dept_id) 기준 분석. legacy job_descriptions active JD 를 사용합니다.
    공고 중심 전환으로 신규 개발 대상이 아닙니다(프론트 런타임 호출 없음). 신규 분석은 공고 기준
    /analyze-posting · /analyze-selected · /analyze-all (모두 analyze_posting 경로)을 사용하세요.
    하위호환 위해 유지 — 동작 변경 금지, 후속 제거 검토(docs/TODO).

    선택 부서의 분석 대기 파일을 Drive 에서 내려받아 JD 기준으로 분석하고,
    성공 파일은 completed, 실패 파일은 failed 로 이동합니다. (파일 단위 성공/실패)

    인증 단계와 사전검증/분석 처리 단계를 분리해 step 을 정확히 반환합니다.
    (인증이 정상인데 JD/폴더 매핑/분석에서 실패한 것을 'token 생성 실패' 로 보고하지 않습니다.)
    """
    _log("[resume-analysis] ===== /api/resumes/analyze-pending start =====")

    # 1) 선택 부서 확인 (프론트는 JSON body 로 dept_id 를 보냅니다.)
    dept_id = (body.dept_id or "").strip()
    if not dept_id:
        _log("[resume-analysis] error step = dept_required")
        return _error("dept_required", "분석 대상 부서가 선택되지 않았습니다.",
                      "왼쪽 부서/팀 트리에서 분석 대상 팀을 선택해주세요.")
    _log(f"[resume-analysis] dept_id = {dept_id}")

    # 1-1) 분석 실행 권한 검사 — 반드시 Drive 인증/분석/상태변경/OpenAI 호출 전에 수행
    #      ADMIN 전체 / MANAGER 본인 하위 / VIEWER 불가. 권한 없으면 HTTPException(401 은 의존성).
    ensure_can_run_analysis(db, current_user, dept_id)

    # 2) Google Drive 인증 + service build (실패 시 step 별 에러 JSON)
    service, drive_err = _build_drive_service_or_error()
    if drive_err is not None:
        return drive_err

    # 3) 분석 실행 (JD/폴더 매핑 등 사전검증, 파일단위 실패는 서비스가 step 을 구분)
    try:
        result = ResumeAnalysisService(service).analyze_pending(dept_id, body.upload_id)
    except ResumeAnalysisError as e:
        _log(f"[resume-analysis] error step = {e.step} / type = ResumeAnalysisError / message = {e.message}")
        return _error(e.step, e.message, e.hint)
    except Exception as e:
        _log(f"[resume-analysis] error step = analysis_failed / type = {type(e).__name__}")
        return _error("analysis_failed", "분석 처리 중 오류가 발생했습니다.",
                      "JD/부서 폴더 동기화/Drive 권한을 확인하세요.", 500)

    _log(f"[resume-analysis] done analyzed_count={result.get('completed_count')}, "
         f"failed_count={result.get('failed_count')}")
    return result


def _build_drive_service_or_error():
    """
    Google Drive 인증 + service build 공통 처리. (analyze-pending / analyze-selected / analyze-all 공용)
    반환: (service, None) 성공 / (None, error_JSONResponse) 실패.
    """
    service = GoogleDriveService()
    if not TOKEN_PATH.exists():
        _log("[resume-analysis] error step = google_oauth_token_missing")
        return None, _error("google_oauth_token_missing",
                            "token.json이 없어 Google Drive 인증이 필요합니다.",
                            "서버 터미널에 출력된 OAuth URL을 브라우저에서 열어 인증을 완료해주세요.")
    try:
        creds = service.authenticate()
        if service.token_dirty:
            service.save_token(creds)
    except DriveConfigError as e:
        _log(f"[resume-analysis] error step = google_token_refresh_failed / type = {type(e).__name__}")
        return None, _error("google_token_refresh_failed",
                            "refresh_token으로 access token 갱신에 실패했습니다.",
                            "Google 계정 권한이 제거되었거나 OAuth client/scopes가 변경되었을 수 있습니다.")
    except Exception as e:
        _log(f"[resume-analysis] error step = google_oauth_failed / type = {type(e).__name__}")
        return None, _error("google_oauth_failed", "Google Drive 인증 중 오류가 발생했습니다.",
                            "credentials.json / token.json / OAuth scope를 확인해주세요.", 500)
    try:
        service.build_drive(creds)
    except Exception as e:
        _log(f"[resume-analysis] error step = google_drive_service_build_failed / type = {type(e).__name__}")
        return None, _error("google_drive_service_build_failed",
                            "Google Drive service 생성 중 오류가 발생했습니다.",
                            "credentials.json, token.json, OAuth scope를 확인해주세요.", 500)
    return service, None


def _run_analysis_over_depts(service, dept_to_fileids: dict) -> dict:
    """
    LEGACY HELPER — 부서 기준 분석 집계(analyze_pending 사용). 현재 어떤 엔드포인트에서도 호출되지 않습니다
    (선택/전체 분석은 공고 기준 Celery task(analyze_resume_posting_task)로 대체됨). 신규 사용 금지, 후속 제거 검토(docs/TODO).

    부서별로 분석을 실행하고 집계합니다. (선택 항목/전체 분석 공용)
    dept_to_fileids: {dept_id: [resume_file_id,...] 또는 None}. None 이면 해당 부서 전체 PENDING.
    분석은 부서 단위(JD/폴더가 부서별)라 부서별로 ResumeAnalysisService.analyze_pending 을 호출합니다.
    한 부서의 사전검증 실패(JD/폴더 없음 등)는 dept_errors 로 모으고 다른 부서는 계속 진행합니다.
    """
    total = success = failed = 0
    departments = []
    dept_errors = []
    for dept_id, file_ids in dept_to_fileids.items():
        try:
            r = ResumeAnalysisService(service).analyze_pending(dept_id, resume_file_ids=file_ids)
        except ResumeAnalysisError as e:
            _log(f"[resume-analysis] dept {dept_id} 사전검증 실패: {e.step}: {e.message}")
            dept_errors.append({"dept_id": dept_id, "step": e.step,
                                "message": e.message, "hint": e.hint})
            continue
        except Exception as e:
            _log(f"[resume-analysis] dept {dept_id} 분석 실패: {type(e).__name__}: {e}")
            dept_errors.append({"dept_id": dept_id, "step": "analysis_failed",
                                "message": f"{type(e).__name__}: {e}", "hint": ""})
            continue
        t = r.get("total_pending_files", 0)
        s = r.get("completed_count", 0)
        fcnt = r.get("failed_count", 0)
        total += t
        success += s
        failed += fcnt
        departments.append({"dept_id": dept_id, "dept_name": r.get("dept_name"),
                            "total": t, "success": s, "failed": fcnt})
    message = "분석이 완료되었습니다." if total else "분석 대기 파일이 없습니다."
    return {"status": "OK", "total": total, "success": success, "failed": failed,
            "message": message, "departments": departments, "dept_errors": dept_errors}


@router.get("/posting-pending-counts")
def posting_pending_counts(current_user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """권한 범위 공고별 분석 대기 건수 맵 {posting_id: count}. (분석 작업 관리 공고 리스트용)"""
    allowed_ids = department_access_service.get_accessible_department_ids(db, current_user)
    return resume_analysis_db_service.get_posting_pending_counts(allowed_ids)


@router.get("/posting-pending/{posting_id}")
def posting_pending_files(posting_id: int, page: int = 1, size: int = 20,
                          current_user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """선택 공고의 분석 대기 파일 목록(페이징). (조회 권한: ADMIN 전체 / MANAGER·VIEWER 본인 부서+하위)"""
    posting = job_posting_service.get_posting_entity(db, posting_id)
    department_access_service.ensure_department_access(db, current_user, posting.department_id)
    return resume_analysis_db_service.get_posting_pending_view(posting_id, page=page, size=size)


@router.post("/analyze-posting")
def analyze_posting(body: AnalyzePostingRequest,
                    current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """선택 공고 분석을 **비동기 큐에 등록**합니다(즉시 QUEUED 응답). 실제 분석/Drive 이동/DB 저장은
    Celery worker(resume_analysis 큐)가 공고 active JD 기준으로 수행합니다. (VIEWER/권한 밖 403)"""
    posting = job_posting_service.get_posting_entity(db, body.posting_id)
    # 권한: ADMIN 전체 / MANAGER 본인 부서+하위 / VIEWER 403 (enqueue 전에 차단)
    job_posting_service.ensure_can_manage_posting(db, current_user, posting)
    # 조기 검증: active JD 없으면 enqueue 하지 않음
    if job_posting_service.get_active_jd_entity(db, body.posting_id) is None:
        return _error("active_jd_not_found", "공고에 등록된 활성 JD가 없습니다.",
                      "공고 상세에서 JD를 먼저 등록해주세요.")
    # 중복 enqueue 방지: 진행 중(PROCESSING)이면 skip, 대기(PENDING) 없으면 enqueue 안 함
    counts = resume_analysis_db_service.get_posting_analysis_status_counts(body.posting_id)
    if counts["processing"] > 0:
        return {"status": "ALREADY_PROCESSING", "posting_id": body.posting_id,
                "queue": RESUME_ANALYSIS_QUEUE,
                "message": "이미 분석이 진행 중입니다. 잠시 후 이력서 현황을 확인해주세요."}
    if counts["pending"] == 0:
        return {"status": "NO_PENDING", "posting_id": body.posting_id,
                "message": "분석 대기 파일이 없습니다."}
    try:
        task = analyze_resume_posting_task.delay(body.posting_id, None, current_user.id)
    except Exception as e:
        _log(f"[resume-analysis] enqueue 실패 posting_id={body.posting_id} type={type(e).__name__}")
        return _error("enqueue_failed", "분석 작업을 큐에 등록하지 못했습니다.",
                      "잠시 후 다시 시도하거나 관리자에게 문의해주세요.", 503)
    _log(f"[resume-analysis] queued posting_id={body.posting_id} task_id={task.id} "
         f"pending={counts['pending']} by={current_user.id}")
    return {"status": "QUEUED", "message": "이력서 분석 작업이 큐에 등록되었습니다.",
            "posting_id": body.posting_id, "task_id": task.id,
            "queue": RESUME_ANALYSIS_QUEUE, "pending_count": counts["pending"]}


@router.post("/analyze-selected")
def analyze_selected(body: AnalyzeSelectedRequest,
                     current_user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """
    체크된 resume_file_id 목록만 분석합니다. (프론트 체크박스를 믿지 않고 백엔드에서 재검증)
    - 공고 기준: 각 파일의 posting_id 의 active JD 로 분석합니다.
    - 권한: 각 파일의 공고가 권한 범위여야 함 (하나라도 밖이면 403, VIEWER 도 403)
    - 대상: 실제 PENDING 인 파일만 (이미 분석된 항목 제외)
    """
    ids = list(dict.fromkeys(body.resume_file_ids or []))  # 중복 제거(순서 유지)
    if not ids:
        return _error("no_selection", "분석할 항목을 선택해주세요.",
                      "테이블에서 분석할 파일을 1개 이상 선택해주세요.")

    rows = resume_analysis_db_service.get_files_dept_and_status(ids)
    found = {r["id"] for r in rows}
    missing = [i for i in ids if i not in found]
    if missing:
        return _error("resume_file_not_found", f"존재하지 않는 파일이 포함되어 있습니다: {missing}",
                      "목록을 새로고침한 뒤 다시 시도해주세요.", 404)

    # 공고 미매핑(legacy) 파일은 공고 기준 분석 대상이 아닙니다.
    unmapped = [r["id"] for r in rows if not r.get("posting_id")]
    if unmapped:
        return _error("posting_unmapped_files", f"공고에 매핑되지 않은 파일이 포함되어 있습니다: {unmapped}",
                      "공고/JD 기준으로 업로드된 이력서만 분석할 수 있습니다.")

    # 권한 검사: 선택 파일들의 모든 공고가 권한 범위여야 함 (하나라도 밖이면 403). VIEWER 도 여기서 403.
    for pid in {r["posting_id"] for r in rows}:
        posting = job_posting_service.get_posting_entity(db, pid)
        job_posting_service.ensure_can_manage_posting(db, current_user, posting)

    # 실제 PENDING(UPLOADED+PENDING) 만 대상으로 (이미 분석된/처리중 항목 제외)
    pending_rows = [r for r in rows
                    if r["file_status"] == "UPLOADED" and r["analysis_status"] == "PENDING"]
    if not pending_rows:
        return {"status": "OK", "total": 0, "success": 0, "failed": 0,
                "message": "분석 대기 파일이 없습니다.", "postings": [], "posting_errors": []}

    posting_to_fileids = {}
    for r in pending_rows:
        posting_to_fileids.setdefault(r["posting_id"], []).append(r["id"])

    # 공고 그룹별로 선택 파일 분석 task 를 비동기 큐에 등록(즉시 QUEUED 응답).
    tasks = []
    try:
        for pid, fids in posting_to_fileids.items():
            task = analyze_resume_posting_task.delay(pid, fids, current_user.id)
            tasks.append({"posting_id": pid, "resume_file_count": len(fids), "task_id": task.id})
    except Exception as e:
        _log(f"[resume-analysis] selected enqueue 실패 type={type(e).__name__}")
        return _error("enqueue_failed", "분석 작업을 큐에 등록하지 못했습니다.",
                      "잠시 후 다시 시도해주세요.", 503)
    total = sum(t["resume_file_count"] for t in tasks)
    _log(f"[resume-analysis] selected queued postings={len(tasks)} files={total} by={current_user.id}")
    return {"status": "QUEUED", "message": "선택한 이력서 분석 작업이 큐에 등록되었습니다.",
            "queue": RESUME_ANALYSIS_QUEUE, "resume_file_count": total, "tasks": tasks}


@router.post("/analyze-all")
def analyze_all(current_user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """
    전체 분석: 공고 기준 분석 대기 파일이 있는 공고들을 **공고 단위 task 여러 개로 비동기 큐에 등록**합니다.
    (scope=all) 대량 작업의 요청 타임아웃을 피하기 위해 공고별로 나눠 enqueue 합니다.
    - **ADMIN 전용** (MANAGER/VIEWER 는 403). 대상 공고는 백엔드에서 계산합니다.
    """
    role = (current_user.role_code or "").upper()
    if role != "ADMIN":
        raise HTTPException(status_code=403, detail="전체 분석은 관리자(ADMIN)만 실행할 수 있습니다.")
    # ADMIN: 전체 공고. 분석 대기(PENDING)가 있는 공고만 대상으로 계산.
    counts = resume_analysis_db_service.get_posting_pending_counts(None)
    posting_ids = list(counts.keys())
    if not posting_ids:
        return {"status": "NO_PENDING", "message": "분석 대기 파일이 없습니다.",
                "queue": RESUME_ANALYSIS_QUEUE, "posting_count": 0, "tasks": []}

    # 공고별로 전체 PENDING 분석 task 를 enqueue(resume_file_ids=None = 공고 전체 PENDING).
    tasks = []
    try:
        for pid in posting_ids:
            task = analyze_resume_posting_task.delay(pid, None, current_user.id)
            tasks.append({"posting_id": pid, "pending_count": counts[pid], "task_id": task.id})
    except Exception as e:
        _log(f"[resume-analysis] all enqueue 실패 type={type(e).__name__}")
        return _error("enqueue_failed", "분석 작업을 큐에 등록하지 못했습니다.",
                      "잠시 후 다시 시도해주세요.", 503)
    total = sum(counts[pid] for pid in posting_ids)
    _log(f"[resume-analysis] all queued postings={len(tasks)} files={total} by={current_user.id}")
    return {"status": "QUEUED", "message": "전체 공고의 이력서 분석 작업이 큐에 등록되었습니다.",
            "queue": RESUME_ANALYSIS_QUEUE, "posting_count": len(tasks),
            "resume_file_count": total, "tasks": tasks}
