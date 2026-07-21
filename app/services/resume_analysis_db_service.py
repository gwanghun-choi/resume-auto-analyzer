from datetime import datetime

from app.db.session import resolve_session
from app.db.models.resume_file import ResumeFile
from app.db.models.resume_upload_batch import ResumeUploadBatch
from app.db.models.resume_analysis_result import ResumeAnalysisResult
from app.db.models.job_posting import JobPosting
from app.db.models.job_posting_jd import JobPostingJD
from app.db.models.department import Department

# resume_analysis_db_service 는 resume_ai.resume_files / resume_upload_batches /
# resume_analysis_results 만 다룹니다. (ORM 모델이 schema=resume_ai 로 묶여 있어 다른 스키마는 안 건드림)
#
# 분석 결과의 '기준 저장소'는 이제 DB(resume_analysis_results) 입니다.
# (analysis_results.json 은 fallback/debug 용도로만 병행 저장)


def get_pending_files_for_analysis(dept_id: str, upload_id: str = None,
                                   resume_file_ids: list = None, session=None) -> list:
    """
    분석 대상(PENDING) 파일을 DB 에서 조회합니다.
    조건: dept_id, file_status=UPLOADED, analysis_status=PENDING.
      - upload_id 있으면 해당 회차만
      - resume_file_ids 있으면 그 id 들만 (선택 항목 분석용; 부서 내에서 추가로 좁힘)
    이동에 필요한 batch 정보(upload_folder_name / drive_upload_folder_id)도 함께 반환합니다.
    """
    session, _own = resolve_session(session)
    try:
        query = (
            session.query(ResumeFile, ResumeUploadBatch)
            .join(ResumeUploadBatch, ResumeFile.upload_id == ResumeUploadBatch.upload_id)
            .filter(
                ResumeFile.dept_id == dept_id,
                ResumeFile.file_status == "UPLOADED",
                ResumeFile.analysis_status == "PENDING",
            )
        )
        if upload_id:
            query = query.filter(ResumeFile.upload_id == upload_id)
        if resume_file_ids is not None:
            query = query.filter(ResumeFile.id.in_(resume_file_ids))
        query = query.order_by(ResumeFile.created_at.asc(), ResumeFile.id.asc())

        out = []
        for f, b in query.all():
            out.append({
                "resume_file_id": f.id,
                "upload_id": f.upload_id,
                "dept_id": f.dept_id,
                "original_file_name": f.original_file_name,
                "stored_file_name": f.stored_file_name,
                "drive_file_id": f.drive_file_id,
                "file_size": f.file_size,
                "content_type": f.content_type,
                "extension": f.extension,
                "upload_folder_name": b.upload_folder_name,
                "drive_upload_folder_id": b.drive_upload_folder_id,
            })
        return out
    finally:
        if _own:
            session.close()


def get_files_dept_and_status(resume_file_ids: list, session=None) -> list:
    """
    resume_file_id 목록의 부서/공고/상태를 조회합니다. (선택 항목 분석의 권한·PENDING 재검증용)
    반환: [{id, dept_id, posting_id, file_status, analysis_status}]  (존재하는 것만)
    """
    if not resume_file_ids:
        return []
    session, _own = resolve_session(session)
    try:
        rows = (
            session.query(
                ResumeFile.id, ResumeFile.dept_id, ResumeFile.posting_id,
                ResumeFile.file_status, ResumeFile.analysis_status,
            )
            .filter(ResumeFile.id.in_(resume_file_ids))
            .all()
        )
        return [
            {"id": r[0], "dept_id": r[1], "posting_id": r[2],
             "file_status": r[3], "analysis_status": r[4]}
            for r in rows
        ]
    finally:
        if _own:
            session.close()


# ===== 공고(posting) 기준 분석 =====

def get_posting_analysis_context(posting_id: int, session=None) -> dict:
    """
    공고 기준 분석에 필요한 컨텍스트를 조회합니다.
    반환: {posting_id, department_id, dept_name, completed_folder_id, failed_folder_id,
           jd: {id, title, required_skills, preferred_skills, jd_content}} 또는 None(공고 없음).
    jd 가 None 이면 active JD 미등록.
    """
    session, _own = resolve_session(session)
    try:
        p = session.query(JobPosting).filter(JobPosting.id == posting_id).first()
        if not p:
            return None
        dept_name = session.query(Department.name).filter(
            Department.id == p.department_id).scalar()
        jd = (
            session.query(JobPostingJD)
            .filter(JobPostingJD.posting_id == posting_id, JobPostingJD.is_active.is_(True))
            .order_by(JobPostingJD.id.desc())
            .first()
        )
        return {
            "posting_id": p.id,
            "department_id": p.department_id,
            "dept_name": dept_name or "",
            "completed_folder_id": p.drive_completed_folder_id,
            "failed_folder_id": p.drive_failed_folder_id,
            "jd": ({
                "id": jd.id,
                "title": jd.title,
                "required_skills": jd.required_skills or [],
                "preferred_skills": jd.preferred_skills or [],
                "jd_content": jd.jd_content,
            } if jd else None),
        }
    finally:
        if _own:
            session.close()


def get_pending_files_for_posting(posting_id: int, resume_file_ids: list = None,
                                  session=None) -> list:
    """
    공고의 분석 대상(PENDING) 파일을 조회합니다.
    조건: resume_files.posting_id=posting_id, file_status=UPLOADED, analysis_status=PENDING.
    이동에 필요한 batch 정보(upload_folder_name / drive_upload_folder_id)도 함께 반환합니다.
    """
    session, _own = resolve_session(session)
    try:
        query = (
            session.query(ResumeFile, ResumeUploadBatch)
            .join(ResumeUploadBatch, ResumeFile.upload_id == ResumeUploadBatch.upload_id)
            .filter(
                ResumeFile.posting_id == posting_id,
                ResumeFile.file_status == "UPLOADED",
                ResumeFile.analysis_status == "PENDING",
            )
        )
        if resume_file_ids is not None:
            query = query.filter(ResumeFile.id.in_(resume_file_ids))
        query = query.order_by(ResumeFile.created_at.asc(), ResumeFile.id.asc())
        out = []
        for f, b in query.all():
            out.append({
                "resume_file_id": f.id,
                "upload_id": f.upload_id,
                "dept_id": f.dept_id,
                "posting_id": f.posting_id,
                "original_file_name": f.original_file_name,
                "stored_file_name": f.stored_file_name,
                "drive_file_id": f.drive_file_id,
                "file_size": f.file_size,
                "content_type": f.content_type,
                "extension": f.extension,
                "upload_folder_name": b.upload_folder_name,
                "drive_upload_folder_id": b.drive_upload_folder_id,
            })
        return out
    finally:
        if _own:
            session.close()


def get_posting_pending_view(posting_id: int, page: int = 1, size: int = 20,
                             session=None) -> dict:
    """공고의 분석 대기 파일 목록(화면 표시용, 페이징).
    반환: {posting_id, total, page, size, pending_count(=total), files:[현재 페이지]}"""
    page = max(1, int(page))
    size = max(1, min(int(size or 20), 200))
    session, _own = resolve_session(session)
    try:
        base = (
            session.query(ResumeFile)
            .filter(
                ResumeFile.posting_id == posting_id,
                ResumeFile.file_status == "UPLOADED",
                ResumeFile.analysis_status == "PENDING",
            )
        )
        total = base.count()
        files = (
            base.order_by(ResumeFile.created_at.asc(), ResumeFile.id.asc())
            .offset((page - 1) * size).limit(size).all()
        )
        dept_ids = {f.dept_id for f in files if f.dept_id}
        dept_name_map = {}
        if dept_ids:
            dept_name_map = {
                d.id: d.name for d in
                session.query(Department.id, Department.name).filter(Department.id.in_(dept_ids)).all()
            }
        out = []
        for f in files:
            out.append({
                "resume_file_id": f.id,
                "original_file_name": f.original_file_name,
                "dept_id": f.dept_id,
                "dept_name": dept_name_map.get(f.dept_id),
                "upload_id": f.upload_id,
                "uploaded_at": f.created_at.isoformat(timespec="seconds") if f.created_at else None,
            })
        return {"status": "OK", "posting_id": posting_id, "total": total,
                "page": page, "size": size, "pending_count": total, "files": out}
    finally:
        if _own:
            session.close()


def get_posting_pending_counts(allowed_dept_ids: list = None, session=None) -> dict:
    """
    공고별 분석 대기(PENDING) 파일 수를 반환합니다. ('공고 분석' 화면의 대기 건수 표시용)
    반환: {posting_id: pending_count}. allowed_dept_ids=None 이면 전체(ADMIN).
    """
    session, _own = resolve_session(session)
    try:
        q = (
            session.query(ResumeFile.posting_id)
            .filter(
                ResumeFile.posting_id.isnot(None),
                ResumeFile.file_status == "UPLOADED",
                ResumeFile.analysis_status == "PENDING",
            )
        )
        if allowed_dept_ids is not None:
            q = q.filter(ResumeFile.dept_id.in_(allowed_dept_ids))
        counts = {}
        for (pid,) in q.all():
            counts[pid] = counts.get(pid, 0) + 1
        return counts
    finally:
        if _own:
            session.close()


def get_posting_analysis_status_counts(posting_id: int, session=None) -> dict:
    """공고의 이력서 분석 상태별 건수(UPLOADED 파일 기준). 비동기 중복 enqueue 방지/대기 여부 판단용.
    반환: {"pending": n, "processing": n, "completed": n, "failed": n}."""
    session, _own = resolve_session(session)
    try:
        vals = [r[0] for r in session.query(ResumeFile.analysis_status).filter(
            ResumeFile.posting_id == posting_id,
            ResumeFile.file_status == "UPLOADED",
        ).all()]
        return {
            "pending": sum(1 for v in vals if v == "PENDING"),
            "processing": sum(1 for v in vals if v == "PROCESSING"),
            "completed": sum(1 for v in vals if v == "COMPLETED"),
            "failed": sum(1 for v in vals if v == "FAILED"),
        }
    finally:
        if _own:
            session.close()


def get_pending_dept_ids(allowed_dept_ids: list = None, session=None) -> list:
    """
    분석 대기(PENDING) 파일이 있는 부서 id 목록(중복 제거)을 반환합니다. ('전체 분석' 대상 부서 계산용)
    allowed_dept_ids=None 이면 전체(ADMIN), 리스트면 해당 부서들로 제한(MANAGER).
    """
    session, _own = resolve_session(session)
    try:
        q = (
            session.query(ResumeFile.dept_id)
            .filter(
                ResumeFile.file_status == "UPLOADED",
                ResumeFile.analysis_status == "PENDING",
            )
            .distinct()
        )
        if allowed_dept_ids is not None:
            q = q.filter(ResumeFile.dept_id.in_(allowed_dept_ids))
        return [r[0] for r in q.all()]
    finally:
        if _own:
            session.close()


def set_processing(resume_file_id: int, session=None) -> None:
    """분석 시작 시 resume_files.analysis_status 를 PROCESSING 으로 바꿉니다."""
    session, _own = resolve_session(session)
    try:
        session.query(ResumeFile).filter(ResumeFile.id == resume_file_id).update(
            {ResumeFile.analysis_status: "PROCESSING", ResumeFile.updated_at: datetime.now()},
            synchronize_session=False,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if _own:
            session.close()


def save_result(file_meta: dict, analysis_id: str, success: bool, analysis: dict,
                moved_to, move_status: str, moved_drive_file_id, analyzed_at: datetime,
                error_code, error_message,
                posting_id=None, jd_id=None, jd_snapshot=None, session=None) -> None:
    """
    분석 결과를 한 트랜잭션으로 저장합니다.
      - resume_analysis_results insert (성공/실패 모두)
      - resume_files 업데이트 (analysis_status/move/score/recommendation/error 등)
    공고 기준 분석이면 posting_id/jd_id/jd_snapshot 도 함께 기록합니다(없으면 None).
    실패 시 rollback.
    """
    now = datetime.now()
    analysis_status = "COMPLETED" if success else "FAILED"
    score = int(round(analysis["score"])) if (success and analysis.get("score") is not None) else None

    session, _own = resolve_session(session)
    try:
        session.add(ResumeAnalysisResult(
            analysis_id=analysis_id,
            resume_file_id=file_meta["resume_file_id"],
            upload_id=file_meta["upload_id"],
            dept_id=file_meta["dept_id"],
            posting_id=posting_id,
            jd_id=jd_id,
            jd_snapshot=jd_snapshot,
            original_file_name=file_meta["original_file_name"],
            stored_file_name=file_meta["stored_file_name"],
            drive_file_id=file_meta["drive_file_id"],
            completed_drive_file_id=(moved_drive_file_id if success else None),
            source_drive_folder="inbox",
            moved_to=moved_to,
            analysis_status=analysis_status,
            move_status=move_status,
            score=score,
            recommendation=(analysis["recommendation"] if success else None),
            summary=(analysis["summary"] if success else None),
            strengths=(analysis["strengths"] if success else None),
            weaknesses=(analysis["weaknesses"] if success else None),
            matched_skills=(analysis["matched_skills"] if success else None),
            missing_skills=(analysis["missing_skills"] if success else None),
            reasoning=(analysis["reasoning"] if success else None),
            error_code=(None if success else error_code),
            error_message=(None if success else error_message),
            raw_response=(analysis.get("raw_response") if success else None),
            analyzed_at=analyzed_at,
        ))
        session.query(ResumeFile).filter(ResumeFile.id == file_meta["resume_file_id"]).update(
            {
                ResumeFile.analysis_status: analysis_status,
                ResumeFile.move_status: move_status,
                ResumeFile.moved_to: moved_to,
                ResumeFile.moved_drive_file_id: moved_drive_file_id,
                ResumeFile.score: score,
                ResumeFile.recommendation: (analysis["recommendation"] if success else None),
                ResumeFile.error_code: (None if success else error_code),
                ResumeFile.error_message: (None if success else error_message),
                ResumeFile.analyzed_at: analyzed_at,
                ResumeFile.updated_at: now,
            },
            synchronize_session=False,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if _own:
            session.close()


def _batch_status(vals: list) -> str:
    if not vals:
        return "UPLOADED"
    if all(v == "COMPLETED" for v in vals):
        return "ANALYSIS_COMPLETED"
    if all(v == "FAILED" for v in vals):
        return "ANALYSIS_FAILED"
    if any(v in ("PENDING", "PROCESSING") for v in vals):
        return "PARTIAL_ANALYZED"
    return "ANALYSIS_PARTIAL_FAILED"


def update_batch_counts(upload_id: str, session=None) -> dict:
    """upload_id 의 resume_files 를 집계해 batch 의 카운트/상태를 갱신합니다."""
    session, _own = resolve_session(session)
    try:
        vals = [r[0] for r in session.query(ResumeFile.analysis_status).filter(
            ResumeFile.upload_id == upload_id
        ).all()]
        completed = sum(1 for v in vals if v == "COMPLETED")
        failed = sum(1 for v in vals if v == "FAILED")
        pending = sum(1 for v in vals if v == "PENDING")
        status = _batch_status(vals)
        session.query(ResumeUploadBatch).filter(ResumeUploadBatch.upload_id == upload_id).update(
            {
                ResumeUploadBatch.completed_count: completed,
                ResumeUploadBatch.failed_count: failed,
                ResumeUploadBatch.pending_count: pending,
                ResumeUploadBatch.status: status,
                ResumeUploadBatch.updated_at: datetime.now(),
            },
            synchronize_session=False,
        )
        session.commit()
        return {"status": status, "completed_count": completed,
                "failed_count": failed, "pending_count": pending}
    except Exception:
        session.rollback()
        raise
    finally:
        if _own:
            session.close()


def get_batch(upload_id: str, session=None) -> dict:
    """batch 의 폴더 정보를 반환합니다. (inbox 폴더 정리용)"""
    session, _own = resolve_session(session)
    try:
        b = session.query(ResumeUploadBatch).filter(
            ResumeUploadBatch.upload_id == upload_id
        ).first()
        if not b:
            return None
        return {
            "upload_id": b.upload_id,
            "drive_upload_folder_id": b.drive_upload_folder_id,
            "upload_folder_name": b.upload_folder_name,
        }
    finally:
        if _own:
            session.close()


def save_batch_cleanup(upload_id: str, cleanup: dict, session=None) -> None:
    """inbox upload 폴더 정리 결과를 batch.inbox_upload_folder_cleanup(JSONB)에 저장합니다."""
    session, _own = resolve_session(session)
    try:
        session.query(ResumeUploadBatch).filter(ResumeUploadBatch.upload_id == upload_id).update(
            {ResumeUploadBatch.inbox_upload_folder_cleanup: cleanup,
             ResumeUploadBatch.updated_at: datetime.now()},
            synchronize_session=False,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if _own:
            session.close()
