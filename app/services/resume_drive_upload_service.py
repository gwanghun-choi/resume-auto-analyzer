import io
import json
import mimetypes
import os
import tempfile
import zipfile
from datetime import datetime

from app.services.google_drive_service import GoogleDriveService, PROJECT_ROOT, _log
from app.services import resume_upload_db_service

# ResumeDriveUploadService 는 이력서 등록 화면에서 올린 파일을
# 선택한 부서의 Google Drive inbox/{upload_folder_name} 폴더에 저장하고 기록을 남깁니다.
#
# 업로드 기록의 '기준 저장소'는 이제 DB(resume_ai.resume_upload_batches / resume_files) 입니다.
#   - upload_records.json 은 fallback/debug 용도로만 병행 저장합니다.
#   - AI 분석 / 텍스트 추출 / LLM 호출 / completed·failed 이동은 하지 않습니다.
#   - 지원자 1명 = 파일 1개로 간주합니다. (묶음 처리 없음)

# dept_id -> inbox_folder_id 매핑 (부서 폴더 동기화 결과)
MAP_PATH = PROJECT_ROOT / "data" / "google_drive" / "dept_folder_map.json"
# 업로드 기록 (DB 대체)
RECORDS_DIR = PROJECT_ROOT / "data" / "google_drive"
RECORDS_PATH = RECORDS_DIR / "upload_records.json"

# 허용 확장자 (zip 은 '컨테이너' 로만 사용하고 일반 파일로 저장하지 않습니다)
ALLOWED_EXTS = {"pdf", "doc", "docx", "hwp", "hwpx", "txt", "md", "rtf", "csv", "json"}
CONTAINER_EXT = "zip"
# 실행 가능/위험 확장자 (업로드 금지)
BLOCKED_EXTS = {"exe", "bat", "sh", "js", "html", "htm", "ps1", "cmd", "msi", "dll"}

# 크기/개수 제한
MAX_FILE_BYTES = 20 * 1024 * 1024      # 개별 파일 20MB
MAX_TOTAL_BYTES = 100 * 1024 * 1024    # 전체 업로드 100MB
MAX_ZIP_ENTRIES = 100                  # zip 내부 파일 최대 100개


class ResumeUploadError(Exception):
    """업로드를 진행할 수 없는 사용자/설정 오류. (라우터에서 step/hint JSON 으로 변환)"""
    def __init__(self, message: str, step: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.step = step
        self.hint = hint


def _ext(name: str) -> str:
    _, dot, ext = name.rpartition(".")
    return ext.lower() if dot else ""


def _basename(name: str) -> str:
    return os.path.basename(name.replace("\\", "/"))


def _is_hidden_or_system(name: str) -> bool:
    base = _basename(name)
    return (not base) or base.startswith(".") or ("__MACOSX" in name)


def _sanitize_filename(name: str) -> str:
    """경로 구분자/제어문자/위험문자를 _ 로 치환합니다. (경로 부분은 버리고 파일명만 사용)"""
    base = _basename(name)
    out = []
    for ch in base:
        if ch in '/\\<>:"|?*' or ord(ch) < 32:
            out.append("_")
        else:
            out.append(ch)
    cleaned = "".join(out).strip()
    return cleaned or "file"


def _strip_ext(name: str) -> str:
    base = _basename(name)
    stem, dot, _ = base.rpartition(".")
    return stem if dot else base


def _make_source_label(raw: str) -> str:
    """
    원본 업로드 파일명(확장자 제거)에서 표시용 라벨을 만듭니다.
    주의: source_label 은 '후보자명' 이 아니라 업로드 회차를 사람이 알아보기 위한 표시값입니다.
    위험문자 _ 치환 + 50자 제한.
    """
    out = []
    for ch in raw:
        if ch in '/\\:*?"<>|' or ord(ch) < 32:
            out.append("_")
        else:
            out.append(ch)
    cleaned = "".join(out).strip()[:50]
    return cleaned or "upload"


class ResumeDriveUploadService:
    def __init__(self, drive: GoogleDriveService):
        # 이미 인증/build 까지 끝난 GoogleDriveService 를 주입받습니다.
        self._drive = drive

    def upload(self, dept_id: str, files: list, *, inbox_entry: dict = None,
               posting_id: int = None, jd_id: int = None) -> dict:
        """
        files: [{"filename", "content_type", "data"(bytes)}, ...]
        선택 부서(또는 공고)의 inbox/{upload_folder_name} 폴더에 업로드하고 결과 dict 를 반환합니다.

        - inbox_entry 가 주어지면 그 inbox_folder_id 를 사용합니다(공고 기준 업로드).
          이때 dept_id 는 공고 부서(posting.department_id)이며 resume_files.dept_id 로 저장됩니다.
        - posting_id/jd_id 가 주어지면 resume_files 에 함께 저장됩니다.
        - inbox_entry 가 없으면 기존 부서 매핑(dept_drive_folders)에서 inbox 를 찾습니다(legacy).
        """
        entry = inbox_entry if inbox_entry is not None else self._lookup_inbox(dept_id)
        inbox_id = entry["inbox_folder_id"]
        dept_name = entry.get("dept_name", "")
        folder_name = entry.get("folder_name") or f"{dept_id}_{dept_name}"

        # upload_type / source_label 결정 → upload_folder_name 생성
        upload_type, source_upload_file_name, source_label = self._classify(files)
        upload_id = "UPL" + datetime.now().strftime("%Y%m%d_%H%M%S")
        _log(f"[resume-upload] upload_id = {upload_id}")
        desired_folder = f"{upload_id}_{source_label}"
        # 업로드 회차 폴더 생성 (Drive 오류는 폴더 생성 실패 step 으로 구분)
        try:
            upload_folder_name = self._drive.make_unique_folder_name(inbox_id, desired_folder)
            upload_folder_id = self._drive.create_folder_if_not_exists(inbox_id, upload_folder_name)
        except ResumeUploadError:
            raise
        except Exception as e:
            _log(f"[resume-upload] upload folder 생성 실패: {type(e).__name__}: {e}")
            raise ResumeUploadError(
                "Google Drive 업로드 폴더 생성 중 오류가 발생했습니다.",
                step="drive_upload_folder_create_failed",
                hint="Drive 폴더 권한과 부서 폴더 매핑을 확인해주세요.",
            ) from e
        drive_path_display = f"resume-demo-root/inbox/{folder_name}/{upload_folder_name}"
        _log(f"[resume-upload] upload_folder_name = {upload_folder_name}")
        _log(f"[resume-upload] drive upload folder id = {upload_folder_id}")
        _log(f"[resume-upload] {dept_id} -> {drive_path_display} (type={upload_type})")

        # 요청 단위 상태
        self._folder_id = upload_folder_id
        self._uploaded = []
        self._skipped = []   # 제외/실패 모두 여기에 (reason 포함)
        self._used_names = set()
        self._total_bytes = 0

        with tempfile.TemporaryDirectory() as tmp:
            self._tmp = tmp
            for f in files:
                self._handle_top_level(f)

        uploaded_count = len(self._uploaded)
        skipped_count = len(self._skipped)
        if uploaded_count == 0:
            upload_status, resp_status = "UPLOAD_FAILED", "ERROR"
        elif skipped_count > 0:
            upload_status, resp_status = "PARTIAL_UPLOADED", "OK"
        else:
            upload_status, resp_status = "UPLOADED", "OK"

        # 업로드 회차 메타 (응답/기록 공통)
        meta = {
            "upload_id": upload_id,
            "upload_folder_name": upload_folder_name,
            "source_upload_file_name": source_upload_file_name,
            "source_label": source_label,
            "upload_type": upload_type,
            "dept_id": dept_id,
            "dept_name": dept_name,
            "drive_upload_folder_id": upload_folder_id,
            "drive_path_display": drive_path_display,
            "posting_id": posting_id,   # 공고 기준 업로드일 때만 값 존재(없으면 None=legacy)
            "jd_id": jd_id,
        }

        # (fallback/debug) upload_records.json 에도 병행 저장
        record = {
            **meta,
            "source": "web_upload",
            "status": upload_status,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "files": self._uploaded,
            "skipped_files": self._skipped,
        }
        record_saved, record_error = self._append_record(record)

        result = {
            "status": resp_status,
            **meta,
            "upload_status": upload_status,
            "uploaded_count": uploaded_count,
            "skipped_count": skipped_count,
            "uploaded_files": self._uploaded,
            "skipped_files": self._skipped,
            "record_saved": record_saved,
        }
        if not record_saved:
            result["record_save_error"] = record_error
        if resp_status == "ERROR":
            result["step"] = "no_uploadable_files"
            result["error_message"] = "업로드 가능한 이력서 파일이 없습니다."
            result["hint"] = "허용 확장자(PDF/DOC/DOCX/HWP/HWPX/TXT/MD/RTF/CSV/JSON/ZIP) 파일을 업로드하세요."

        # 기준 저장소: DB(resume_ai.resume_upload_batches + resume_files)
        # Drive 업로드는 성공했는데 DB 저장만 실패하면 PARTIAL_SUCCESS 로 구분합니다.
        try:
            db_saved = resume_upload_db_service.save_upload(
                meta, self._uploaded, uploaded_count, skipped_count, upload_status,
            )
            result["db_save_status"] = "OK"
            result["db_saved"] = db_saved
        except Exception as e:
            _log(f"[resume-upload] DB 저장 실패: {type(e).__name__}: {e}")
            result["db_save_status"] = "FAILED"
            if resp_status == "OK":
                # Drive 성공 / DB 실패 → PARTIAL_SUCCESS (이미 올라간 Drive 파일은 삭제하지 않음)
                result["status"] = "PARTIAL_SUCCESS"
                result["drive_upload_status"] = "OK"
                result["error_message"] = "Google Drive 업로드는 성공했지만 DB 저장에 실패했습니다."
                result["hint"] = "DB 상태를 확인한 뒤 업로드 기록을 복구해야 합니다."
        return result

    def _classify(self, files: list):
        """
        업로드 묶음에서 upload_type / source_upload_file_name / source_label 을 정합니다.
        - 단일 일반 파일: SINGLE_FILE, 단일 zip: ZIP (둘 다 파일명 기반 라벨)
        - 여러 파일: MULTIPLE_FILES / (zip 포함 시) MIXED_FILES, 라벨은 'multi'
        """
        n = len(files)
        has_zip = any(_ext(f.get("filename") or "") == CONTAINER_EXT for f in files)
        if n == 1:
            name = files[0].get("filename") or ""
            upload_type = "ZIP" if _ext(name) == CONTAINER_EXT else "SINGLE_FILE"
            return upload_type, name, _make_source_label(_strip_ext(name))
        upload_type = "MIXED_FILES" if has_zip else "MULTIPLE_FILES"
        return upload_type, "multiple_files", "multi"

    # ----- 내부 처리 -----

    def _lookup_inbox(self, dept_id: str) -> dict:
        """
        dept_id 의 inbox 매핑을 **DB(resume_ai.dept_drive_folders)** 에서 찾습니다.
        DB 에 없으면(또는 DB 오류 시) dept_folder_map.json 으로 fallback 합니다.

        - 매핑(행) 자체가 없으면: dept_drive_folder_mapping_not_found
        - 매핑은 있는데 inbox_folder_id 만 없으면: dept_inbox_folder_missing
        """
        _log("[resume-upload] lookup dept_drive_folders start")
        found_row = None  # 매핑 행은 있으나 inbox_folder_id 가 없는 경우 구분용

        # 1) DB 우선
        try:
            from app.services import dept_drive_folder_db_service
            row = dept_drive_folder_db_service.get_folder(dept_id)
            if row:
                found_row = row
                if row.get("inbox_folder_id"):
                    _log("[resume-upload] folder mapping found = true")
                    _log(f"[resume-upload] inbox_folder_id = {row.get('inbox_folder_id')}")
                    return row
        except Exception as e:
            _log(f"[resume-upload] dept_drive_folders DB 조회 실패 → map.json fallback: {type(e).__name__}: {e}")

        # 2) fallback: dept_folder_map.json
        if MAP_PATH.exists():
            try:
                mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
                entry = mapping.get(dept_id)
                if entry:
                    found_row = found_row or entry
                    if entry.get("inbox_folder_id"):
                        _log("[resume-upload] folder mapping found = true (map.json)")
                        _log(f"[resume-upload] inbox_folder_id = {entry.get('inbox_folder_id')}")
                        return entry
            except (ValueError, json.JSONDecodeError):
                pass

        # 매핑은 있는데 inbox_folder_id 만 없는 경우
        if found_row is not None:
            _log("[resume-upload] folder mapping found = true, inbox_folder_id = none")
            raise ResumeUploadError(
                "선택한 부서의 inbox 폴더 ID가 없습니다.",
                step="dept_inbox_folder_missing",
                hint="관리자 > Google Drive 동기화에서 부서 폴더 동기화를 다시 실행해주세요.",
            )
        # 매핑 자체가 없는 경우
        _log("[resume-upload] folder mapping found = false")
        raise ResumeUploadError(
            "선택한 부서의 Google Drive 폴더 매핑을 찾을 수 없습니다.",
            step="dept_drive_folder_mapping_not_found",
            hint="관리자 > Google Drive 동기화에서 Drive config 기준 전체 동기화를 먼저 실행해주세요.",
        )

    def _reject_reason(self, name: str, allow_zip_container: bool):
        """이 파일을 제외해야 하면 사유 문자열을, 업로드 대상이면 None 을 반환합니다."""
        if _is_hidden_or_system(name):
            return "unsupported_or_hidden_file"
        ext = _ext(name)
        if ext in BLOCKED_EXTS:
            return "blocked_executable_file"
        if ext == CONTAINER_EXT:
            return None if allow_zip_container else "nested_zip_not_supported"
        if ext not in ALLOWED_EXTS:
            return "unsupported_extension"
        return None

    def _handle_top_level(self, f: dict):
        name = f.get("filename") or ""
        reason = self._reject_reason(name, allow_zip_container=True)
        if reason:
            self._skipped.append({"original_file_name": name, "reason": reason})
            return
        if _ext(name) == CONTAINER_EXT:
            self._process_zip(f["data"], name)
            return
        self._upload_bytes(name, f["data"], f.get("content_type"))

    def _process_zip(self, zip_bytes: bytes, zip_name: str):
        """zip 을 임시 메모리에서 풀어 허용 파일만 평탄화 업로드합니다. (중첩 zip 미처리)"""
        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except zipfile.BadZipFile:
            self._skipped.append({"original_file_name": zip_name, "reason": "invalid_zip"})
            return
        with zf:
            accepted = 0
            for zi in zf.infolist():
                if zi.is_dir():
                    continue
                raw = zi.filename
                norm = raw.replace("\\", "/")
                # path traversal / 절대경로 차단
                if norm.startswith("/") or ".." in norm.split("/"):
                    self._skipped.append({"original_file_name": raw, "reason": "path_traversal_blocked"})
                    continue
                base = _basename(norm)
                reason = self._reject_reason(base, allow_zip_container=False)
                if reason:
                    self._skipped.append({"original_file_name": base, "reason": reason})
                    continue
                if accepted >= MAX_ZIP_ENTRIES:
                    self._skipped.append({"original_file_name": base, "reason": "zip_entry_limit_exceeded"})
                    continue
                if zi.file_size > MAX_FILE_BYTES:
                    self._skipped.append({"original_file_name": base, "reason": "file_too_large"})
                    continue
                accepted += 1
                self._upload_bytes(base, zf.read(zi), None)

    def _upload_bytes(self, original_name: str, data: bytes, content_type):
        """파일 1건을 임시 파일로 쓴 뒤 Drive 에 업로드합니다. (중복명 방지)"""
        if len(data) > MAX_FILE_BYTES:
            self._skipped.append({"original_file_name": original_name, "reason": "file_too_large"})
            return
        if self._total_bytes + len(data) > MAX_TOTAL_BYTES:
            self._skipped.append({"original_file_name": original_name, "reason": "total_size_limit_exceeded"})
            return

        safe = _sanitize_filename(original_name)
        unique = self._drive.make_unique_file_name(self._folder_id, safe, reserved=self._used_names)
        self._used_names.add(unique)
        tmp_path = os.path.join(self._tmp, unique)
        mime = content_type or mimetypes.guess_type(unique)[0] or "application/octet-stream"
        try:
            with open(tmp_path, "wb") as out:
                out.write(data)
            file_id = self._drive.upload_file_to_folder(tmp_path, self._folder_id, unique, mime)
        except Exception as e:
            _log(f"[resume-upload] Drive 업로드 실패: {original_name}: {type(e).__name__}: {e}")
            self._skipped.append({"original_file_name": original_name, "reason": f"drive_upload_failed: {e}"})
            return
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        self._total_bytes += len(data)
        self._uploaded.append({
            "original_file_name": original_name,
            "stored_file_name": unique,
            "drive_file_id": file_id,
            "file_size": len(data),
            "content_type": mime,
            "extension": _ext(original_name),
            "status": "UPLOADED",
            "analysis_status": "PENDING",   # 이번 단계는 분석 안 함 → 항상 PENDING
        })

    def _append_record(self, record: dict):
        """upload_records.json 에 append 저장합니다. (없으면 생성). (saved, error) 반환."""
        try:
            RECORDS_DIR.mkdir(parents=True, exist_ok=True)
            records = []
            if RECORDS_PATH.exists():
                try:
                    loaded = json.loads(RECORDS_PATH.read_text(encoding="utf-8"))
                    if isinstance(loaded, list):
                        records = loaded
                except (ValueError, json.JSONDecodeError):
                    records = []
            records.append(record)
            RECORDS_PATH.write_text(
                json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return True, None
        except Exception as e:
            _log(f"[resume-upload] upload_records.json 저장 실패: {type(e).__name__}: {e}")
            return False, str(e)


def _read_records() -> list:
    """upload_records.json 을 읽습니다. 없거나 깨졌으면 빈 리스트."""
    if not RECORDS_PATH.exists():
        return []
    try:
        loaded = json.loads(RECORDS_PATH.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, list) else []
    except (ValueError, json.JSONDecodeError):
        return []


def get_pending_uploads(dept_id: str) -> dict:
    """
    선택 부서의 '분석 대기 파일'(status=UPLOADED & analysis_status=PENDING)을 모아 반환합니다.
    (Drive 인증 불필요 — 로컬 upload_records.json 만 읽습니다.)
    이전 기록 호환: upload_folder_name/source_label 등이 없으면 fallback 으로 채웁니다.
    """
    records = _read_records()
    dept_name = ""
    uploads = []
    pending_count = 0

    for rec in records:
        if rec.get("dept_id") != dept_id:
            continue
        if rec.get("status") not in ("UPLOADED", "PARTIAL_UPLOADED"):
            continue
        dept_name = rec.get("dept_name", dept_name)

        pending_files = [
            {**f, "analysis_status": f.get("analysis_status", "PENDING")}
            for f in rec.get("files", [])
            if f.get("status", "UPLOADED") == "UPLOADED"
            and f.get("analysis_status", "PENDING") == "PENDING"
        ]
        if not pending_files:
            continue
        pending_count += len(pending_files)

        # 이전 기록 호환용 fallback
        upload_folder_name = rec.get("upload_folder_name") or rec.get("upload_id")
        source_upload_file_name = rec.get("source_upload_file_name")
        source_label = (
            rec.get("source_label")
            or rec.get("source_upload_base_name")
            or rec.get("source_upload_file_name")
            or rec.get("upload_id")
        )
        uploads.append({
            "upload_id": rec.get("upload_id"),
            "upload_folder_name": upload_folder_name,
            "source_upload_file_name": source_upload_file_name,
            "source_label": source_label,
            "upload_type": rec.get("upload_type"),
            "dept_id": rec.get("dept_id"),
            "dept_name": rec.get("dept_name"),
            "drive_upload_folder_id": rec.get("drive_upload_folder_id"),
            "drive_path_display": rec.get("drive_path_display"),
            "created_at": rec.get("created_at"),
            "files": pending_files,
        })

    # 최신 업로드가 위로 오도록 created_at 내림차순 정렬
    uploads.sort(key=lambda u: u.get("created_at") or "", reverse=True)
    return {
        "status": "OK",
        "dept_id": dept_id,
        "dept_name": dept_name,
        "pending_count": pending_count,
        "uploads": uploads,
    }
