import json
import os
import tempfile
from datetime import datetime
from types import SimpleNamespace

from app.services.google_drive_service import GoogleDriveService, PROJECT_ROOT, _log
from app.services.resume_drive_upload_service import MAP_PATH
from app.services.jd_service import JDService
from app.services import jd_db_service
from app.services import dept_drive_folder_db_service
from app.services import resume_analysis_db_service
from app.services.resume_parser_service import ResumeParserService
from app.services.ai_agent_service import AiAgentService
from app.services.matching_service import MatchingService
from app.services.openai_llm_service import OpenAILLMError, api_key_present

# ResumeAnalysisService 는 '분석 대기 파일(resume_ai.resume_files PENDING)' 을 Google Drive 에서 내려받아
# 선택 부서의 JD(DB) 기준으로 분석하고, 결과를 **DB(resume_ai.resume_analysis_results)** 에 저장한 뒤
# 파일을 completed/failed 로 '이동' 하고 resume_files / resume_upload_batches 상태를 갱신합니다.
#
# 기존 파이프라인 재사용: ResumeParserService(텍스트추출) + AiAgentService(LLM) + MatchingService(점수)
# 정책:
#  - 파일 1개 = 지원자 1명. 파일 단위로 성공/실패 처리 (한 파일 실패가 전체를 막지 않음).
#  - completed/failed 이동은 '파일 단위', upload_folder 통째 이동 금지.
#  - Drive 이동은 parent 변경 방식(삭제/재업로드/휴지통 아님).
#  - analysis_results.json 은 fallback/debug 용도로만 병행 저장.

ANALYSIS_RESULTS_PATH = PROJECT_ROOT / "data" / "google_drive" / "analysis_results.json"

# 텍스트로 바로 읽을 수 있는 확장자 (pdf/docx 는 파서 사용)
_PLAIN_TEXT_EXTS = {"txt", "md", "csv", "json"}
MAX_TEXT_CHARS = 20000   # LLM 에 넘길 최대 길이


def _recommendation_for_score(score) -> str:
    """점수 구간별 추천 문구. (batch_service 와 동일 정책 — 탈락/불합격 표현 금지)"""
    if score >= 80:
        return "우선 검토 추천"
    if score >= 60:
        return "추가 검토 필요"
    return "낮은 적합도"


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


class ResumeAnalysisError(Exception):
    """분석 자체를 시작할 수 없는 요청 단위 오류. (라우터에서 step/hint JSON 으로 변환)"""
    def __init__(self, message: str, step: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.step = step
        self.hint = hint


class _ExtractError(Exception):
    """파일 단위 텍스트 추출/다운로드 실패. (전체 중단 없이 해당 파일만 FAILED)"""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ResumeAnalysisService:
    def __init__(self, drive: GoogleDriveService):
        self._drive = drive
        self._parser = ResumeParserService()
        self._matcher = MatchingService()
        self._ai = None  # 지연 생성 (LLM 키 없을 때 생성 비용/오류 회피)
        self._ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    def _ai_service(self) -> AiAgentService:
        if self._ai is None:
            self._ai = AiAgentService()
        return self._ai

    def analyze_pending(self, dept_id: str, upload_id: str = None,
                        resume_file_ids: list = None) -> dict:
        # LEGACY: 부서(dept_id) 기준 분석 진입점. legacy job_descriptions(jd_db_service)의 active JD 를 사용합니다.
        #         공고 중심 전환으로 신규 개발 대상이 아닙니다. 신규/비동기(Celery) 분석은 analyze_posting 만 사용하세요.
        #         (analyze_router / resumes_router 의 /analyze-pending·_run_analysis_over_depts(legacy) 에서만 호출.)
        # --- 요청 단위 선검증 (실패 시 정확한 step 반환) ---
        # OpenAI API key 가 없으면 파일 다운로드/분석 시작 전에 명확히 반환합니다.
        if not api_key_present():
            raise ResumeAnalysisError(
                "OPENAI_API_KEY가 설정되어 있지 않습니다.", "openai_api_key_missing",
                ".env 파일에 OPENAI_API_KEY를 설정한 뒤 서버를 재시작해주세요.",
            )
        # JD 는 DB(resume_ai.job_descriptions)의 active JD 기준으로 조회합니다.
        _log("[resume-analysis] active_jd query start")
        if jd_db_service.get_active(dept_id) is None:
            _log("[resume-analysis] active_jd found = false")
            raise ResumeAnalysisError(
                "선택한 부서의 활성 JD를 찾을 수 없습니다.", "active_jd_not_found",
                "JD 등록 화면에서 해당 부서의 JD를 먼저 저장해주세요.",
            )
        _log("[resume-analysis] active_jd found = true")
        jd = JDService().get(dept_id)

        # Drive 폴더 매핑은 DB(resume_ai.dept_drive_folders) 기준
        _log("[resume-analysis] folder mapping query start")
        entry = self._lookup_map(dept_id)
        _log("[resume-analysis] folder mapping found = true")
        dept_name = entry.get("dept_name", "")
        completed_id = entry.get("completed_folder_id")
        failed_id = entry.get("failed_folder_id")
        _log(f"[resume-analysis] completed_folder_id = {completed_id}")
        _log(f"[resume-analysis] failed_folder_id = {failed_id}")
        if not completed_id or not failed_id:
            raise ResumeAnalysisError(
                "선택한 부서의 completed 또는 failed 폴더 ID가 없습니다.",
                "dept_completed_failed_folder_missing",
                "관리자 > Google Drive 동기화에서 부서 폴더 동기화를 다시 실행해주세요.",
            )

        # 분석 대상은 DB(resume_ai.resume_files PENDING) 기준
        # resume_file_ids 가 주어지면 그 파일들로만 좁힙니다. (선택 항목 분석)
        _log("[resume-analysis] pending query start")
        targets = resume_analysis_db_service.get_pending_files_for_analysis(
            dept_id, upload_id, resume_file_ids)
        _log(f"[resume-analysis] pending_count = {len(targets)}")
        if not targets:
            # 대기 파일이 없는 것은 에러가 아니라 정상(OK) 입니다.
            return {
                "status": "OK", "step": "no_pending_resumes", "source": "db",
                "dept_id": dept_id, "dept_name": dept_name, "requested_upload_id": upload_id,
                "message": "분석 대기 파일이 없습니다.",
                "total_pending_files": 0, "completed_count": 0, "failed_count": 0, "results": [],
            }

        out = self._process_targets(jd, dept_name, completed_id, failed_id, targets)
        out["dept_id"] = dept_id
        out["requested_upload_id"] = upload_id
        return out

    def analyze_posting(self, posting_id: int, resume_file_ids: list = None) -> dict:
        """
        공고(posting_id) 기준 분석. resume_file.posting_id 의 active JD(job_posting_jds)로 분석하고,
        공고 Drive completed/failed 폴더로 이동합니다. (MatchingService 산식/프롬프트 불변)
        - resume_file_ids 가 주어지면 그 파일들로만 좁힙니다(선택 항목 분석).
        - 분석 결과에 posting_id/jd_id/jd_snapshot 을 함께 저장합니다.
        """
        if not api_key_present():
            raise ResumeAnalysisError(
                "OPENAI_API_KEY가 설정되어 있지 않습니다.", "openai_api_key_missing",
                ".env 파일에 OPENAI_API_KEY를 설정한 뒤 서버를 재시작해주세요.",
            )
        ctx = resume_analysis_db_service.get_posting_analysis_context(posting_id)
        if ctx is None:
            raise ResumeAnalysisError("공고를 찾을 수 없습니다.", "posting_not_found",
                                      "공고/JD 목록을 새로고침한 뒤 다시 시도해주세요.")
        if ctx["jd"] is None:
            raise ResumeAnalysisError(
                "공고에 등록된 활성 JD를 찾을 수 없습니다.", "active_jd_not_found",
                "공고 상세에서 JD를 먼저 등록해주세요.",
            )
        completed_id = ctx["completed_folder_id"]
        failed_id = ctx["failed_folder_id"]
        if not completed_id or not failed_id:
            raise ResumeAnalysisError(
                "공고의 completed 또는 failed 폴더 ID가 없습니다.",
                "posting_completed_failed_folder_missing",
                "공고를 다시 등록하거나 관리자에게 문의해주세요.",
            )
        jd_data = ctx["jd"]
        jd = SimpleNamespace(
            position_title=(jd_data["title"] or ""),
            required_skills=jd_data["required_skills"],
            preferred_skills=jd_data["preferred_skills"],
        )
        jd_snapshot = {
            "title": jd_data["title"],
            "required_skills": jd_data["required_skills"],
            "preferred_skills": jd_data["preferred_skills"],
            "jd_content": jd_data["jd_content"],
        }
        dept_name = ctx["dept_name"]

        targets = resume_analysis_db_service.get_pending_files_for_posting(posting_id, resume_file_ids)
        _log(f"[resume-analysis] posting={posting_id} pending_count = {len(targets)}")
        if not targets:
            return {
                "status": "OK", "step": "no_pending_resumes", "source": "db",
                "posting_id": posting_id, "dept_id": ctx["department_id"], "dept_name": dept_name,
                "message": "분석 대기 파일이 없습니다.",
                "total_pending_files": 0, "completed_count": 0, "failed_count": 0, "results": [],
            }

        out = self._process_targets(jd, dept_name, completed_id, failed_id, targets,
                                    posting_id=posting_id, jd_id=jd_data["id"], jd_snapshot=jd_snapshot)
        out["posting_id"] = posting_id
        out["dept_id"] = ctx["department_id"]
        return out

    def _process_targets(self, jd, dept_name, completed_id, failed_id, targets,
                         posting_id=None, jd_id=None, jd_snapshot=None) -> dict:
        """대상 파일 리스트를 분석하고 batch 카운트/빈 폴더 정리까지 수행하는 공용 처리부.
        (부서 기준 analyze_pending / 공고 기준 analyze_posting 공용)"""
        results = []
        json_records = []   # 병행 analysis_results.json (debug)
        completed_count = failed_count = 0
        db_save_status = "OK"
        affected_uploads = []
        for t in targets:
            if t["upload_id"] not in affected_uploads:
                affected_uploads.append(t["upload_id"])
            res = self._process_one_db(jd, dept_name, completed_id, failed_id, t,
                                       posting_id=posting_id, jd_id=jd_id, jd_snapshot=jd_snapshot)
            results.append(res["response"])
            json_records.append(res["record"])
            if res["db_save_status"] == "FAILED":
                db_save_status = "PARTIAL"
            if res["response"]["analysis_status"] == "COMPLETED":
                completed_count += 1
            else:
                failed_count += 1

        # 영향받은 upload_id 들의 batch 카운트/상태 갱신 + 빈 inbox 폴더 정리
        updated_batches = []
        cleanups = []
        warnings = []
        for uid in affected_uploads:
            try:
                counts = resume_analysis_db_service.update_batch_counts(uid)
                updated_batches.append({"upload_id": uid, **counts})
            except Exception as e:
                _log(f"[analysis] batch 카운트 갱신 실패: {uid}: {e}")
                warnings.append(f"batch_count_update_failed:{uid}")
                counts = {"status": "PARTIAL_ANALYZED"}
            cleanups.append(self._cleanup_inbox_folder_db(uid, counts))

        # 병행(fallback/debug): analysis_results.json append
        try:
            self._append_analysis_results(json_records)
        except Exception as e:
            _log(f"[analysis] analysis_results.json 병행 저장 실패(무시): {e}")

        return {
            "status": "OK", "source": "db", "dept_name": dept_name,
            "total_pending_files": len(targets),
            "completed_count": completed_count, "failed_count": failed_count,
            "db_save_status": db_save_status,
            "results": results,
            "updated_batches": updated_batches,
            "empty_inbox_folder_cleanups": cleanups,
            "warnings": warnings,
        }

    def _cleanup_inbox_folder_db(self, upload_id: str, counts: dict) -> dict:
        """
        분석/이동이 끝난 upload 의 inbox 폴더가 비었으면 폴더만 휴지통으로 정리합니다.
        - 해당 upload 의 모든 파일이 COMPLETED/FAILED 일 때만 정리 후보 (batch status 로 판단)
        - 폴더가 비어 있을 때만 정리 (이동 실패로 파일이 남아 있으면 정리 안 함)
        - cleanup 실패는 분석 실패로 보지 않고 warning(CLEANUP_FAILED) 으로만 기록
        - 부서 폴더가 아니라 upload_folder 만 대상. 결과는 batch.inbox_upload_folder_cleanup 에 저장
        """
        batch = resume_analysis_db_service.get_batch(upload_id)
        folder_id = batch.get("drive_upload_folder_id") if batch else None
        folder_name = (batch.get("upload_folder_name") if batch else None) or upload_id
        all_done = counts.get("status") in (
            "ANALYSIS_COMPLETED", "ANALYSIS_FAILED", "ANALYSIS_PARTIAL_FAILED",
        )

        if not all_done:
            status = {"was_empty": False, "cleanup_status": "SKIPPED_PENDING_FILES"}
        elif not folder_id:
            status = {"was_empty": None, "cleanup_status": "CLEANUP_FAILED"}
        else:
            try:
                status = self._drive.cleanup_empty_folder(folder_id)
            except Exception as e:
                _log(f"[analysis] inbox 폴더 정리 실패: {folder_name}: {type(e).__name__}: {e}")
                status = {"was_empty": None, "cleanup_status": "CLEANUP_FAILED"}

        cleanup = {
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "folder_id": folder_id,
            "folder_name": folder_name,
            "was_empty": status.get("was_empty"),
            "cleanup_status": status["cleanup_status"],
        }
        try:
            resume_analysis_db_service.save_batch_cleanup(upload_id, cleanup)
        except Exception as e:
            _log(f"[analysis] cleanup 결과 저장 실패(무시): {upload_id}: {e}")

        return {"upload_id": upload_id, "upload_folder_name": folder_name, "checked": True,
                "folder_id": folder_id, "was_empty": status.get("was_empty"),
                "cleanup_status": status["cleanup_status"]}

    # ----- 파일 1건 처리 (DB 기준) -----

    def _process_one_db(self, jd, dept_name, completed_id, failed_id, t,
                        posting_id=None, jd_id=None, jd_snapshot=None) -> dict:
        file_id = t["resume_file_id"]
        analysis_id = f"ANL{self._ts}_{file_id}"
        analyzed_at = datetime.now()
        analyzed_at_str = analyzed_at.isoformat(timespec="seconds")
        upload_folder_name = t["upload_folder_name"] or t["upload_id"]
        from_folder = t["drive_upload_folder_id"]
        stored = t["stored_file_name"] or t["original_file_name"] or "file"
        original = t["original_file_name"] or stored
        drive_file_id = t["drive_file_id"]

        _log(f"[resume-analysis] file start resume_file_id={file_id}, file_name={original}")
        _log(f"[resume-analysis] drive_file_id = {drive_file_id}")

        # 1) 분석 시작 → PROCESSING (DB)
        resume_analysis_db_service.set_processing(file_id)

        # 2) 다운로드 → 텍스트 추출 → AI 분석
        analysis = None
        error_code = error_message = None
        try:
            # 파일에 drive_file_id 가 없으면 파일 단위 실패로 처리합니다.
            if not drive_file_id:
                raise _ExtractError("drive_file_id_missing", "이력서 파일의 Google Drive file id가 없습니다.")
            with tempfile.TemporaryDirectory() as tmp:
                local = os.path.join(tmp, stored)
                try:
                    _log("[resume-analysis] drive download start")
                    self._drive.download_file(drive_file_id, local)
                    _log("[resume-analysis] drive download success")
                except Exception as e:
                    raise _ExtractError("drive_download_failed", f"Drive 다운로드 실패: {e}")
                with open(local, "rb") as fh:
                    content = fh.read()
                text = self._extract_text(stored, content)
                analysis = self._run_ai(jd, text)
        except _ExtractError as e:
            error_code, error_message = e.code, e.message
        except Exception as e:
            error_code, error_message = self._ai_error_code(e), f"{type(e).__name__}: {e}"

        success = analysis is not None
        moved_to = "completed" if success else "failed"
        target_folder_id = completed_id if success else failed_id

        # 3) Drive 파일 이동 (성공/실패 모두 이동. 이동 실패해도 결과는 DB 저장)
        move_status = "MOVED_TO_COMPLETED" if success else "MOVED_TO_FAILED"
        try:
            target = self._drive.create_folder_if_not_exists(target_folder_id, upload_folder_name)
            unique = self._drive.make_unique_file_name(target, stored)
            self._drive.move_file_to_folder(
                drive_file_id, from_folder, target,
                new_name=(unique if unique != stored else None),
            )
        except Exception as e:
            move_status = "MOVE_FAILED"
            _log(f"[analysis] 이동 실패: {stored}: {type(e).__name__}: {e}")

        analysis_status = "COMPLETED" if success else "FAILED"
        moved_drive_file_id = drive_file_id  # parent 변경 방식이라 file_id 동일

        # 4) DB 저장 (resume_analysis_results insert + resume_files update, 한 트랜잭션)
        db_save_status = "OK"
        try:
            resume_analysis_db_service.save_result(
                t, analysis_id, success, analysis, moved_to, move_status,
                moved_drive_file_id, analyzed_at, error_code, error_message,
                posting_id=posting_id, jd_id=jd_id, jd_snapshot=jd_snapshot,
            )
        except Exception as e:
            db_save_status = "FAILED"
            _log(f"[analysis] DB 결과 저장 실패: file_id={file_id}: {type(e).__name__}: {e}")

        # 응답 + analysis_results.json(병행) 용 레코드
        record = {
            "analysis_id": analysis_id, "resume_file_id": file_id, "upload_id": t["upload_id"],
            "dept_id": t["dept_id"], "original_file_name": original, "stored_file_name": stored,
            "drive_file_id": drive_file_id, "source_drive_folder": "inbox", "moved_to": moved_to,
            "analysis_status": analysis_status, "move_status": move_status,
            "analyzed_at": analyzed_at_str,
        }
        if success:
            record.update({
                "completed_drive_file_id": moved_drive_file_id,
                "score": int(round(analysis["score"])), "recommendation": analysis["recommendation"],
                "summary": analysis["summary"], "strengths": analysis["strengths"],
                "weaknesses": analysis["weaknesses"], "matched_skills": analysis["matched_skills"],
                "missing_skills": analysis["missing_skills"], "reasoning": analysis["reasoning"],
            })
        else:
            record.update({"error_code": error_code, "error_message": error_message})

        response = dict(record)
        response["db_save_status"] = db_save_status
        return {"response": response, "record": record, "db_save_status": db_save_status}

    def _extract_text(self, stored: str, content: bytes) -> str:
        ext = _ext(stored)
        if ext == "pdf":
            text = self._safe_parse(self._parser.extract_text_from_pdf, content)
        elif ext == "docx":
            text = self._safe_parse(self._parser.extract_text_from_docx, content)
        elif ext in _PLAIN_TEXT_EXTS:
            text = content.decode("utf-8", errors="replace")
        else:
            raise _ExtractError("unsupported_file_type", f"지원하지 않는 파일 형식입니다: {ext or 'unknown'}")
        if not text or not text.strip():
            raise _ExtractError("empty_text", "텍스트 추출 결과가 비어 있습니다.")
        return text[:MAX_TEXT_CHARS]

    def _safe_parse(self, fn, content: bytes) -> str:
        try:
            return fn(content)
        except Exception as e:
            detail = getattr(e, "detail", None) or str(e)
            if "없" in detail or "empty" in str(detail).lower():
                raise _ExtractError("empty_text", detail)
            raise _ExtractError("text_extract_failed", detail)

    def _run_ai(self, jd, text: str) -> dict:
        ai = self._ai_service().analyze(
            resume_text=text, position=jd.position_title,
            required_skills=jd.required_skills, preferred_skills=jd.preferred_skills,
        )
        match = self._matcher.calculate_match(
            extracted_skills=ai.get("extracted_skills", []),
            required_skills=jd.required_skills, preferred_skills=jd.preferred_skills,
            ai_judgment_score=ai.get("ai_judgment_score", 0),
        )
        score = match["match_score"]
        return {
            "score": score,
            "recommendation": _recommendation_for_score(score),
            "summary": ai.get("candidate_summary", "") or ai.get("career_summary", ""),
            "strengths": ai.get("strengths", []),
            "weaknesses": ai.get("weaknesses", []),
            "matched_skills": match["matched_required_skills"] + match["matched_preferred_skills"],
            "missing_skills": match["missing_required_skills"],
            "reasoning": match["reasoning"],
            "raw_response": ai,   # LLM 원본(파싱된) 응답 — resume_analysis_results.raw_response 에 저장
        }

    def _ai_error_code(self, e: Exception) -> str:
        # OpenAI 호출/파싱 실패는 OpenAILLMError 의 step 을 그대로 파일 단위 코드로 사용합니다.
        if isinstance(e, OpenAILLMError):
            return e.step
        msg = str(e).lower()
        if "json" in msg or "parse" in msg or "decode" in msg:
            return "openai_response_parse_failed"
        return "llm_call_failed"

    # ----- 매핑/기록 파일 -----

    def _lookup_map(self, dept_id: str) -> dict:
        """
        dept_id 의 폴더 매핑(completed/failed 등)을 **DB(resume_ai.dept_drive_folders)** 에서 찾습니다.
        DB 에 없으면(또는 DB 오류 시) dept_folder_map.json 으로 fallback 합니다.
        """
        no_map = ResumeAnalysisError(
            "선택한 부서의 Google Drive 폴더 매핑을 찾을 수 없습니다.",
            "dept_drive_folder_mapping_not_found",
            "관리자 > Google Drive 동기화에서 Drive config 기준 전체 동기화를 먼저 실행해주세요.",
        )
        # 1) DB 우선
        try:
            row = dept_drive_folder_db_service.get_folder(dept_id)
            if row:
                return row
        except Exception as e:
            _log(f"[resume-analysis] dept_drive_folders DB 조회 실패 → map.json fallback: {type(e).__name__}: {e}")

        # 2) fallback: dept_folder_map.json
        if MAP_PATH.exists():
            try:
                mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
                entry = mapping.get(dept_id)
                if entry:
                    return entry
            except (ValueError, json.JSONDecodeError):
                pass
        raise no_map

    def _append_analysis_results(self, new_records: list) -> None:
        existing = []
        if ANALYSIS_RESULTS_PATH.exists():
            try:
                loaded = json.loads(ANALYSIS_RESULTS_PATH.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    existing = loaded
            except (ValueError, json.JSONDecodeError):
                existing = []
        existing.extend(new_records)
        ANALYSIS_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        ANALYSIS_RESULTS_PATH.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )
