from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import resolve_session
from app.db.models.resume_upload_batch import ResumeUploadBatch
from app.db.models.resume_file import ResumeFile

# resume_upload_db_service 는 resume_ai.resume_upload_batches / resume_ai.resume_files 만 다룹니다.
# (ORM 모델이 schema=resume_ai 로 묶여 있어 다른 스키마는 절대 건드리지 않습니다.)
#
# 이력서 업로드 기록의 '기준 저장소'는 이제 DB 입니다.
# (upload_records.json 은 fallback/debug 용도로만 병행 저장)

# resume_upload_batches 에서 upload_id 충돌 시 갱신할 컬럼
_BATCH_UPSERT_COLS = [
    "dept_id", "dept_name", "upload_folder_name", "source_upload_file_name",
    "source_label", "upload_type", "drive_upload_folder_id", "drive_path_display",
    "status", "uploaded_count", "skipped_count", "completed_count",
    "failed_count", "pending_count",
]


def save_upload(meta: dict, uploaded_files: list, uploaded_count: int,
                skipped_count: int, upload_status: str, session=None) -> dict:
    """
    업로드 회차(resume_upload_batches) 1건 + 파일(resume_files) N건을 한 트랜잭션으로 저장합니다.
    - upload_id 기준 batch upsert
    - 파일은 (upload_id, drive_file_id) 또는 (upload_id, stored_file_name) 기준 중복 방지
    - 둘 중 하나라도 실패하면 rollback. 반환: {"resume_upload_batches": 1, "resume_files": N}
    """
    now = datetime.now()
    session, _own = resolve_session(session)
    try:
        batch_row = {
            "upload_id": meta["upload_id"],
            "dept_id": meta["dept_id"],
            "dept_name": meta.get("dept_name"),
            "upload_folder_name": meta["upload_folder_name"],
            "source_upload_file_name": meta.get("source_upload_file_name"),
            "source_label": meta.get("source_label"),
            "upload_type": meta.get("upload_type"),
            "drive_upload_folder_id": meta.get("drive_upload_folder_id"),
            "drive_path_display": meta.get("drive_path_display"),
            "status": upload_status,
            "uploaded_count": uploaded_count,
            "skipped_count": skipped_count,
            "completed_count": 0,
            "failed_count": 0,
            "pending_count": uploaded_count,
        }
        stmt = pg_insert(ResumeUploadBatch).values(batch_row)
        update_set = {c: stmt.excluded[c] for c in _BATCH_UPSERT_COLS}
        update_set["updated_at"] = now
        stmt = stmt.on_conflict_do_update(index_elements=["upload_id"], set_=update_set)
        session.execute(stmt)

        # 같은 upload_id 의 기존 파일(재실행 대비)을 읽어 중복 방지
        existing = session.query(ResumeFile.drive_file_id, ResumeFile.stored_file_name).filter(
            ResumeFile.upload_id == meta["upload_id"]
        ).all()
        seen_drive = {e[0] for e in existing if e[0]}
        seen_names = {e[1] for e in existing if e[1]}

        saved_files = 0
        for f in uploaded_files:
            drive_file_id = f.get("drive_file_id")
            stored_name = f.get("stored_file_name")
            if drive_file_id and drive_file_id in seen_drive:
                continue
            if not drive_file_id and stored_name and stored_name in seen_names:
                continue
            session.add(ResumeFile(
                upload_id=meta["upload_id"],
                dept_id=meta["dept_id"],
                posting_id=meta.get("posting_id"),   # 공고 기준 업로드 시 저장(없으면 None=미매핑)
                jd_id=meta.get("jd_id"),
                original_file_name=f.get("original_file_name"),
                stored_file_name=stored_name,
                drive_file_id=drive_file_id,
                file_size=f.get("file_size"),
                content_type=f.get("content_type"),
                extension=f.get("extension"),
                file_status=f.get("status", "UPLOADED"),
                analysis_status="PENDING",
            ))
            if drive_file_id:
                seen_drive.add(drive_file_id)
            if stored_name:
                seen_names.add(stored_name)
            saved_files += 1

        session.commit()
        return {"resume_upload_batches": 1, "resume_files": saved_files}
    except Exception:
        session.rollback()
        raise
    finally:
        if _own:
            session.close()


def _file_to_dict(f: ResumeFile) -> dict:
    return {
        "id": f.id,
        "original_file_name": f.original_file_name,
        "stored_file_name": f.stored_file_name,
        "drive_file_id": f.drive_file_id,
        "file_size": f.file_size,
        "content_type": f.content_type,
        "extension": f.extension,
        "file_status": f.file_status,
        # 기존 프론트 호환: status 도 file_status 와 동일하게 함께 내려줍니다.
        "status": f.file_status,
        "analysis_status": f.analysis_status,
    }


def _group_pending_uploads(session, files: list, default_dept_id=None) -> list:
    """
    pending 필터된 resume_files 를 upload_id(batch) 별로 묶어 uploads 리스트로 만듭니다.
    (batch.created_at 내림차순. batch 가 없으면 default_dept_id 로 dept_id 를 채웁니다.)
    get_pending_uploads_from_db(단일 부서) / get_pending_uploads_for_scope(권한 범위 전체) 공용.
    """
    upload_ids = {f.upload_id for f in files}
    batches = {
        b.upload_id: b
        for b in session.query(ResumeUploadBatch).filter(
            ResumeUploadBatch.upload_id.in_(upload_ids)
        ).all()
    }

    by_upload = {}
    for f in files:
        by_upload.setdefault(f.upload_id, []).append(f)

    # batch.created_at DESC (없으면 upload_id 역순)
    ordered = sorted(
        upload_ids,
        key=lambda uid: (batches[uid].created_at if uid in batches and batches[uid].created_at
                         else datetime.min),
        reverse=True,
    )

    uploads = []
    for uid in ordered:
        b = batches.get(uid)
        uploads.append({
            "upload_id": uid,
            "upload_folder_name": (b.upload_folder_name if b else uid),
            "source_upload_file_name": (b.source_upload_file_name if b else None),
            "source_label": (b.source_label if b else None),
            "upload_type": (b.upload_type if b else None),
            "dept_id": (b.dept_id if b else default_dept_id),
            "dept_name": (b.dept_name if b else None),
            "drive_upload_folder_id": (b.drive_upload_folder_id if b else None),
            "drive_path_display": (b.drive_path_display if b else None),
            "created_at": (b.created_at.isoformat(timespec="seconds") if b and b.created_at else None),
            "files": [_file_to_dict(f) for f in by_upload[uid]],
        })
    return uploads


def get_pending_uploads_from_db(dept_id: str, session=None) -> dict:
    """
    선택 부서의 '분석 대기 파일'을 **DB** 에서 조회합니다.
    (JSON 기반 get_pending_uploads 와 이름이 겹치지 않도록 _from_db 접미사를 붙입니다.)
    조건: resume_files.dept_id=dept_id AND file_status=UPLOADED AND analysis_status=PENDING.
    회차(batch)별로 묶어 batch.created_at 내림차순으로 반환합니다.
    """
    session, _own = resolve_session(session)
    try:
        files = (
            session.query(ResumeFile)
            .filter(
                ResumeFile.dept_id == dept_id,
                ResumeFile.file_status == "UPLOADED",
                ResumeFile.analysis_status == "PENDING",
            )
            .all()
        )
        if not files:
            return {"status": "OK", "source": "db", "dept_id": dept_id,
                    "dept_name": "", "pending_count": 0, "uploads": []}

        uploads = _group_pending_uploads(session, files, default_dept_id=dept_id)
        dept_name = next((u["dept_name"] for u in uploads if u["dept_name"]), "")
        return {
            "status": "OK", "source": "db", "dept_id": dept_id,
            "dept_name": dept_name, "pending_count": len(files), "uploads": uploads,
        }
    finally:
        if _own:
            session.close()


def get_pending_uploads_for_scope(allowed_dept_ids=None, session=None) -> dict:
    """
    권한 범위 전체의 '분석 대기 파일'을 **DB** 에서 조회합니다. ('전체 부서' 버튼용)
    - allowed_dept_ids=None  : 제한 없음 (ADMIN — 전사 전체)
    - allowed_dept_ids=리스트 : 해당 부서들로만 제한 (MANAGER/VIEWER — 본인 부서 + 하위)
    조건: file_status=UPLOADED AND analysis_status=PENDING (+ dept_id IN allowed).
    반환 구조는 get_pending_uploads_from_db 와 동일(uploads[].files[]). 여러 부서가 섞일 수 있어
    top-level dept_id/dept_name 은 비웁니다. (각 upload 가 자체 dept_id/dept_name 보유)
    """
    session, _own = resolve_session(session)
    try:
        q = session.query(ResumeFile).filter(
            ResumeFile.file_status == "UPLOADED",
            ResumeFile.analysis_status == "PENDING",
        )
        if allowed_dept_ids is not None:
            q = q.filter(ResumeFile.dept_id.in_(allowed_dept_ids))
        files = q.all()
        if not files:
            return {"status": "OK", "source": "db", "scope": "all", "dept_id": None,
                    "dept_name": None, "pending_count": 0, "uploads": []}

        uploads = _group_pending_uploads(session, files)
        return {
            "status": "OK", "source": "db", "scope": "all", "dept_id": None,
            "dept_name": None, "pending_count": len(files), "uploads": uploads,
        }
    finally:
        if _own:
            session.close()


def get_pending_debug(dept_id: str, session=None) -> dict:
    """
    디버그용: 부서의 batch/파일 저장 현황과 pending 조건에 걸리는 파일 수를 빠르게 확인합니다.
    (API 문제와 프론트 문제를 분리하기 위함. resume_ai 만 조회)
    """
    session, _own = resolve_session(session)
    try:
        batches = (
            session.query(ResumeUploadBatch)
            .filter(ResumeUploadBatch.dept_id == dept_id)
            .order_by(ResumeUploadBatch.created_at.desc())
            .all()
        )
        files = (
            session.query(ResumeFile)
            .filter(ResumeFile.dept_id == dept_id)
            .order_by(ResumeFile.id.desc())
            .all()
        )
        pending = [
            f for f in files
            if f.file_status == "UPLOADED" and f.analysis_status == "PENDING"
        ]

        def _is_pending(f):
            return f.file_status == "UPLOADED" and f.analysis_status == "PENDING"

        batch_summ = []
        for b in batches:
            bfiles = [f for f in files if f.upload_id == b.upload_id]
            batch_summ.append({
                "upload_id": b.upload_id,
                "file_count": len(bfiles),
                "pending_file_count": sum(1 for f in bfiles if _is_pending(f)),
            })

        return {
            "status": "OK",
            "dept_id": dept_id,
            "batch_count": len(batches),
            "file_count": len(files),
            "pending_file_count": len(pending),
            "batches": batch_summ,
            "files": [
                {
                    "id": f.id,
                    "upload_id": f.upload_id,
                    "original_file_name": f.original_file_name,
                    "file_status": f.file_status,
                    "analysis_status": f.analysis_status,
                }
                for f in files
            ],
        }
    finally:
        if _own:
            session.close()
