from datetime import datetime, timedelta

from sqlalchemy import or_

from app.db.session import resolve_session
from app.db.models.resume_file import ResumeFile
from app.db.models.resume_upload_batch import ResumeUploadBatch
from app.db.models.resume_analysis_result import ResumeAnalysisResult
from app.db.models.department import Department
from app.db.models.job_posting import JobPosting

# resume_status_db_service 는 이력서 '현황' 조회 전용(읽기 전용) 서비스입니다.
# resume_ai 스키마의 resume_files / resume_upload_batches / departments /
# resume_analysis_results 만 조회합니다.
# (ORM 모델이 schema=resume_ai 로 묶여 있어 다른 스키마는 절대 건드리지 않습니다.)
#
# 조인 기준:
#   resume_files.upload_id = resume_upload_batches.upload_id
#   resume_files.dept_id   = departments.id
#   resume_analysis_results.resume_file_id = resume_files.id (최신 analyzed_at 1건)
# 목록의 점수/추천은 resume_files 요약 컬럼(score/recommendation)을 우선 사용합니다.


def _iso(dt) -> str:
    return dt.isoformat(timespec="seconds") if dt else None


def _apply_filters(query, dept_id, analysis_status, recommendation, keyword, date_from, date_to,
                   allowed_dept_ids=None, posting_id=None, posting_keyword=None):
    """resume_files 기준 공통 필터를 적용합니다. (목록/엑셀 공용)

    allowed_dept_ids: 로그인 사용자 권한 부서 id 리스트. None 이면 전체 허용(ADMIN).
                      리스트면 해당 부서들로만 제한(MANAGER/VIEWER) — 권한 필터.
    posting_id: 특정 공고로 제한. posting_keyword: 공고명 부분일치(해당 공고들로 제한).
    """
    # 권한 필터: ADMIN(None) 은 제한 없음, MANAGER/VIEWER 는 접근 가능 부서로만 제한
    if allowed_dept_ids is not None:
        query = query.filter(ResumeFile.dept_id.in_(allowed_dept_ids))
    if posting_id:
        query = query.filter(ResumeFile.posting_id == posting_id)
    if posting_keyword:
        # 공고명 부분일치 → 해당 공고 id 들로 resume_files 를 제한 (공고 미매핑 파일은 제외됨)
        sub = query.session.query(JobPosting.id).filter(
            JobPosting.title.ilike(f"%{posting_keyword}%")
        )
        query = query.filter(ResumeFile.posting_id.in_(sub.scalar_subquery()))
    if dept_id:
        query = query.filter(ResumeFile.dept_id == dept_id)
    if analysis_status:
        query = query.filter(ResumeFile.analysis_status == analysis_status)
    if recommendation:
        query = query.filter(ResumeFile.recommendation == recommendation)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(or_(
            ResumeFile.original_file_name.ilike(like),
            ResumeFile.stored_file_name.ilike(like),
        ))
    # 업로드일(created_at) 기준 범위 필터. date_to 는 해당 일자까지 포함(다음날 0시 미만)
    if date_from:
        query = query.filter(ResumeFile.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
    if date_to:
        end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(ResumeFile.created_at < end)
    return query


def _name_maps(session, files):
    """파일 목록에서 필요한 batch / dept 이름을 한 번에 조회해 매핑으로 만듭니다."""
    upload_ids = {f.upload_id for f in files}
    dept_ids = {f.dept_id for f in files}
    batches = {}
    if upload_ids:
        batches = {
            b.upload_id: b
            for b in session.query(ResumeUploadBatch).filter(
                ResumeUploadBatch.upload_id.in_(upload_ids)
            ).all()
        }
    depts = {}
    if dept_ids:
        depts = {
            d.id: d.name
            for d in session.query(Department.id, Department.name).filter(
                Department.id.in_(dept_ids)
            ).all()
        }
    # 공고 id -> 공고명 (미매핑 파일은 posting_id 가 None 이라 제외)
    posting_ids = {f.posting_id for f in files if f.posting_id}
    postings = {}
    if posting_ids:
        postings = {
            p.id: p.title
            for p in session.query(JobPosting.id, JobPosting.title).filter(
                JobPosting.id.in_(posting_ids)
            ).all()
        }
    return batches, depts, postings


def get_status_list(dept_id=None, analysis_status=None, recommendation=None,
                    keyword=None, date_from=None, date_to=None, page=1, size=20,
                    allowed_dept_ids=None, posting_id=None, posting_keyword=None,
                    session=None) -> dict:
    """이력서 파일 목록을 DB(resume_ai) 기준으로 조회합니다. (페이징, 권한 부서 필터, 공고 필터)"""
    page = max(1, page)
    size = max(1, min(size, 200))
    session, _own = resolve_session(session)
    try:
        q = _apply_filters(session.query(ResumeFile), dept_id, analysis_status,
                           recommendation, keyword, date_from, date_to, allowed_dept_ids,
                           posting_id=posting_id, posting_keyword=posting_keyword)
        total = q.count()
        files = (
            q.order_by(ResumeFile.created_at.desc(), ResumeFile.id.desc())
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )
        batches, depts, postings = _name_maps(session, files)

        items = []
        for f in files:
            b = batches.get(f.upload_id)
            items.append({
                "resume_file_id": f.id,
                "upload_id": f.upload_id,
                "dept_id": f.dept_id,
                "dept_name": depts.get(f.dept_id) or (b.dept_name if b else None),
                "posting_id": f.posting_id,
                "posting_title": postings.get(f.posting_id) if f.posting_id else None,
                "upload_folder_name": b.upload_folder_name if b else None,
                "source_upload_file_name": b.source_upload_file_name if b else None,
                "upload_type": b.upload_type if b else None,
                "original_file_name": f.original_file_name,
                "stored_file_name": f.stored_file_name,
                "drive_file_id": f.drive_file_id,
                "file_size": f.file_size,
                "content_type": f.content_type,
                "extension": f.extension,
                "file_status": f.file_status,
                "analysis_status": f.analysis_status,
                "move_status": f.move_status,
                "moved_to": f.moved_to,
                "score": f.score,
                "recommendation": f.recommendation,
                "uploaded_at": _iso(f.created_at),
                "analyzed_at": _iso(f.analyzed_at),
            })
        return {"status": "OK", "source": "db", "page": page, "size": size,
                "total": total, "items": items}
    finally:
        if _own:
            session.close()


def _latest_analysis(session, resume_file_id):
    """resume_file_id 의 최신(analyzed_at 기준) 분석 결과 1건을 반환합니다. 없으면 None."""
    return (
        session.query(ResumeAnalysisResult)
        .filter(ResumeAnalysisResult.resume_file_id == resume_file_id)
        .order_by(ResumeAnalysisResult.analyzed_at.desc().nullslast(),
                  ResumeAnalysisResult.analysis_id.desc())
        .first()
    )


def get_file_for_download(resume_file_id: int, session=None) -> dict:
    """
    원본 파일 다운로드 API 용 최소 메타를 조회합니다. 파일 없으면 None.
    반환: id, dept_id, drive_file_id, original_file_name, stored_file_name, content_type.
    """
    session, _own = resolve_session(session)
    try:
        f = session.query(ResumeFile).filter(ResumeFile.id == resume_file_id).first()
        if not f:
            return None
        return {
            "id": f.id,
            "dept_id": f.dept_id,
            "drive_file_id": f.drive_file_id,
            "original_file_name": f.original_file_name,
            "stored_file_name": f.stored_file_name,
            "content_type": f.content_type,
        }
    finally:
        if _own:
            session.close()


def get_status_detail(resume_file_id: int, session=None) -> dict:
    """이력서 파일 1건의 상세 + 업로드 회차 + 최신 분석 결과를 조회합니다. 파일 없으면 None."""
    session, _own = resolve_session(session)
    try:
        f = session.query(ResumeFile).filter(ResumeFile.id == resume_file_id).first()
        if not f:
            return None
        b = session.query(ResumeUploadBatch).filter(
            ResumeUploadBatch.upload_id == f.upload_id
        ).first()
        dept_name = session.query(Department.name).filter(
            Department.id == f.dept_id
        ).scalar()
        posting_title = None
        if f.posting_id:
            posting_title = session.query(JobPosting.title).filter(
                JobPosting.id == f.posting_id
            ).scalar()
        a = _latest_analysis(session, f.id)

        resume_file = {
            "id": f.id,
            "upload_id": f.upload_id,
            "dept_id": f.dept_id,
            "dept_name": dept_name or (b.dept_name if b else None),
            "posting_id": f.posting_id,
            "posting_title": posting_title,
            "jd_id": f.jd_id,
            "original_file_name": f.original_file_name,
            "stored_file_name": f.stored_file_name,
            "drive_file_id": f.drive_file_id,
            "file_size": f.file_size,
            "content_type": f.content_type,
            "extension": f.extension,
            "file_status": f.file_status,
            "analysis_status": f.analysis_status,
            "move_status": f.move_status,
            "moved_to": f.moved_to,
            "moved_drive_file_id": f.moved_drive_file_id,
            "score": f.score,
            "recommendation": f.recommendation,
            "error_code": f.error_code,
            "error_message": f.error_message,
            "created_at": _iso(f.created_at),
            "analyzed_at": _iso(f.analyzed_at),
        }
        upload_batch = None
        if b:
            upload_batch = {
                "upload_id": b.upload_id,
                "upload_folder_name": b.upload_folder_name,
                "source_upload_file_name": b.source_upload_file_name,
                "source_label": b.source_label,
                "upload_type": b.upload_type,
                "drive_upload_folder_id": b.drive_upload_folder_id,
                "drive_path_display": b.drive_path_display,
                "status": b.status,
            }
        analysis_result = None
        if a:
            analysis_result = {
                "analysis_id": a.analysis_id,
                "analysis_status": a.analysis_status,
                "move_status": a.move_status,
                "score": a.score,
                "recommendation": a.recommendation,
                "summary": a.summary,
                "strengths": a.strengths,
                "weaknesses": a.weaknesses,
                "matched_skills": a.matched_skills,
                "missing_skills": a.missing_skills,
                "reasoning": a.reasoning,
                "error_code": a.error_code,
                "error_message": a.error_message,
                "analyzed_at": _iso(a.analyzed_at),
            }
        return {"status": "OK", "source": "db", "resume_file": resume_file,
                "upload_batch": upload_batch, "analysis_result": analysis_result}
    finally:
        if _own:
            session.close()


def get_status_export_rows(dept_id=None, analysis_status=None, recommendation=None,
                           keyword=None, date_from=None, date_to=None,
                           allowed_dept_ids=None, posting_id=None, posting_keyword=None,
                           session=None) -> list:
    """엑셀용: 필터 조건 전체(페이징 없음) 행을 분석 결과까지 합쳐 반환합니다. (권한 부서/공고 필터)"""
    session, _own = resolve_session(session)
    try:
        q = _apply_filters(session.query(ResumeFile), dept_id, analysis_status,
                           recommendation, keyword, date_from, date_to, allowed_dept_ids,
                           posting_id=posting_id, posting_keyword=posting_keyword)
        files = q.order_by(ResumeFile.created_at.desc(), ResumeFile.id.desc()).all()
        batches, depts, postings = _name_maps(session, files)

        # 파일별 최신 분석 결과 매핑 (analyzed_at 오름차순으로 덮어써 마지막이 최신)
        results = {}
        file_ids = [f.id for f in files]
        if file_ids:
            for a in (
                session.query(ResumeAnalysisResult)
                .filter(ResumeAnalysisResult.resume_file_id.in_(file_ids))
                .order_by(ResumeAnalysisResult.analyzed_at.asc().nullsfirst(),
                          ResumeAnalysisResult.analysis_id.asc())
                .all()
            ):
                results[a.resume_file_id] = a

        rows = []
        for f in files:
            b = batches.get(f.upload_id)
            a = results.get(f.id)
            rows.append({
                "dept_id": f.dept_id,
                "dept_name": depts.get(f.dept_id) or (b.dept_name if b else None),
                "posting_id": f.posting_id,
                "posting_title": postings.get(f.posting_id) if f.posting_id else None,
                "upload_id": f.upload_id,
                "upload_folder_name": b.upload_folder_name if b else None,
                "upload_type": b.upload_type if b else None,
                "original_file_name": f.original_file_name,
                "stored_file_name": f.stored_file_name,
                "file_status": f.file_status,
                "analysis_status": f.analysis_status,
                "score": f.score,
                "recommendation": f.recommendation,
                "summary": a.summary if a else None,
                "strengths": a.strengths if a else None,
                "weaknesses": a.weaknesses if a else None,
                "matched_skills": a.matched_skills if a else None,
                "missing_skills": a.missing_skills if a else None,
                "moved_to": f.moved_to,
                "move_status": f.move_status,
                "error_code": f.error_code or (a.error_code if a else None),
                "error_message": f.error_message or (a.error_message if a else None),
                "uploaded_at": _iso(f.created_at),
                "analyzed_at": _iso(f.analyzed_at),
            })
        return rows
    finally:
        if _own:
            session.close()
