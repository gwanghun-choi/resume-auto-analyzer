from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import resolve_session
from app.db.models.dept_drive_folder import DeptDriveFolder

# dept_drive_folder_db_service 는 resume_ai.dept_drive_folders 테이블만 다룹니다.
# 부서별 Google Drive inbox/completed/failed 폴더 ID 매핑을 DB 에 저장/조회합니다.
# (기존 dept_folder_map.json 을 대체. 업로드/분석의 folder_id 조회 기준)

_UPSERT_COLS = [
    "dept_name", "folder_name",
    "inbox_folder_id", "completed_folder_id", "failed_folder_id", "synced_at",
]


def upsert_folder(dept_id: str, dept_name: str, folder_name: str,
                  inbox_folder_id: str, completed_folder_id: str,
                  failed_folder_id: str, session=None) -> str:
    """
    dept_id 기준으로 폴더 매핑을 upsert 합니다. (트랜잭션, 실패 시 rollback)
    반환: 'inserted' 또는 'updated'
    """
    now = datetime.now()
    row = {
        "dept_id": dept_id, "dept_name": dept_name, "folder_name": folder_name,
        "inbox_folder_id": inbox_folder_id,
        "completed_folder_id": completed_folder_id,
        "failed_folder_id": failed_folder_id,
        "synced_at": now,
    }
    session, _own = resolve_session(session)
    try:
        exists = session.query(DeptDriveFolder.id).filter(
            DeptDriveFolder.dept_id == dept_id
        ).first() is not None

        stmt = pg_insert(DeptDriveFolder).values(row)
        update_set = {c: stmt.excluded[c] for c in _UPSERT_COLS}
        update_set["updated_at"] = now
        stmt = stmt.on_conflict_do_update(index_elements=["dept_id"], set_=update_set)
        session.execute(stmt)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if _own:
            session.close()
    return "updated" if exists else "inserted"


def get_folder(dept_id: str, session=None) -> dict:
    """dept_id 의 폴더 매핑을 dict 로 반환합니다. 없으면 None."""
    session, _own = resolve_session(session)
    try:
        r = session.query(DeptDriveFolder).filter(
            DeptDriveFolder.dept_id == dept_id
        ).first()
        if not r:
            return None
        return {
            "dept_id": r.dept_id,
            "dept_name": r.dept_name,
            "folder_name": r.folder_name,
            "inbox_folder_id": r.inbox_folder_id,
            "completed_folder_id": r.completed_folder_id,
            "failed_folder_id": r.failed_folder_id,
        }
    finally:
        if _own:
            session.close()


def count(session=None) -> int:
    session, _own = resolve_session(session)
    try:
        return session.query(DeptDriveFolder).count()
    finally:
        if _own:
            session.close()
