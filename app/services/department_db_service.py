from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import SessionLocal
from app.db.models.department import Department
from app.services.dept_config_service import build_department_tree

# department_db_service 는 resume_ai.departments 테이블만 다룹니다.
# (ORM 모델이 schema=resume_ai 로 묶여 있어 다른 스키마는 절대 건드리지 않습니다.)
#
# 부서 원천은 Google Drive config/dept_config.json 이고, 이 모듈은 그 정규화 결과를
# resume_ai.departments 에 upsert 하고, 화면 트리는 이 테이블 기준으로 조회합니다.

# upsert 시 갱신할 컬럼들 (id 는 충돌 키이므로 제외)
_UPSERT_COLS = [
    "name", "parent_id", "manager_id", "email", "sort", "status",
    "register_date", "update_date", "synced_at",
]


def _parent_id(d: dict):
    parent = d.get("parentId")
    if parent is None:
        parent = d.get("parent_id")
    return parent or None


def _parse_dt(val):
    """ISO 문자열(또는 datetime)을 naive datetime 으로 변환. 실패하면 None."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None)
    try:
        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _to_row(d: dict, now: datetime) -> dict:
    return {
        "id": d.get("id"),
        "name": d.get("name"),
        "parent_id": _parent_id(d),
        "manager_id": d.get("managerId") or d.get("manager_id"),
        "email": d.get("email"),
        "sort": d.get("sort", 0),
        "status": d.get("status", 1),
        "register_date": _parse_dt(d.get("registerDate") or d.get("register_date")),
        "update_date": _parse_dt(d.get("updateDate") or d.get("update_date")),
        "synced_at": now,
    }


def upsert_departments(departments: list) -> dict:
    """
    departments(정규화된 배열)를 resume_ai.departments 에 id 기준 upsert 합니다.
    - JSON 에서 사라진 부서는 삭제하지 않습니다.
    - 트랜잭션으로 처리하고, 실패 시 rollback 합니다.
    반환: {inserted, updated, skipped, total}
    """
    now = datetime.now()
    rows = [_to_row(d, now) for d in departments if isinstance(d, dict)]
    rows = [r for r in rows if r["id"] and r["name"]]
    skipped = len(departments) - len(rows)

    session = SessionLocal()
    try:
        existing_ids = {r[0] for r in session.query(Department.id).all()}
        inserted = sum(1 for r in rows if r["id"] not in existing_ids)
        updated = len(rows) - inserted

        if rows:
            stmt = pg_insert(Department).values(rows)
            update_set = {c: stmt.excluded[c] for c in _UPSERT_COLS}
            update_set["updated_at"] = now
            stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=update_set)
            session.execute(stmt)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return {"inserted": inserted, "updated": updated, "skipped": skipped, "total": len(rows)}


def get_departments(active_only: bool = False) -> list:
    """resume_ai.departments 부서 목록을 dict 리스트로 반환합니다."""
    session = SessionLocal()
    try:
        query = session.query(Department)
        if active_only:
            query = query.filter(Department.status == 1)
        return [
            {"id": r.id, "name": r.name, "parent_id": r.parent_id,
             "sort": r.sort, "status": r.status}
            for r in query.all()
        ]
    finally:
        session.close()


def get_tree(active_only: bool = True) -> list:
    """DB departments 로 부서 트리(중첩 구조)를 구성합니다. (기본: status=1 만)"""
    return build_department_tree(get_departments(active_only=active_only))


def count() -> int:
    session = SessionLocal()
    try:
        return session.query(Department).count()
    finally:
        session.close()
