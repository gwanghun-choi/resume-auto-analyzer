from fastapi import HTTPException
from sqlalchemy import text, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.user import User
from app.db.models.department import Department

# 로그인 사용자의 role_code/department_id 기준으로 '접근 가능한 부서 목록'을 계산합니다.
# - ADMIN  : resume_ai.departments 전체
# - MANAGER/VIEWER : users.department_id(루트) + 모든 하위 부서 (PostgreSQL recursive CTE)
# is_leaf(자식 부서 없음) 면 JD 등록/이력서 업로드 대상(최하위 팀)으로 봅니다.
# 다음 단계(부서 트리 제한, JD/이력서 인가)에서 이 결과를 재사용합니다.

_SCHEMA = settings.DB_SCHEMA  # 신뢰된 설정값(사용자 입력 아님) → 테이블 한정에만 사용

# 각 부서행 + is_leaf(자식 존재 여부의 부정) 을 함께 조회하는 공통 SELECT 입니다.
# ADMIN: 전체 부서
_ADMIN_SQL = text(f"""
    SELECT d.id, d.name, d.parent_id, d.manager_id, d.email,
           NOT EXISTS (
               SELECT 1 FROM {_SCHEMA}.departments c WHERE c.parent_id = d.id
           ) AS is_leaf
    FROM {_SCHEMA}.departments d
    ORDER BY d.id
""")

# MANAGER/VIEWER: :root 부서 + 모든 하위 부서 (recursive CTE)
_SUBTREE_SQL = text(f"""
    WITH RECURSIVE dept_tree AS (
        SELECT id, name, parent_id, manager_id, email
        FROM {_SCHEMA}.departments
        WHERE id = :root
        UNION ALL
        SELECT child.id, child.name, child.parent_id, child.manager_id, child.email
        FROM {_SCHEMA}.departments child
        JOIN dept_tree parent ON child.parent_id = parent.id
    )
    SELECT dt.id, dt.name, dt.parent_id, dt.manager_id, dt.email,
           NOT EXISTS (
               SELECT 1 FROM {_SCHEMA}.departments c WHERE c.parent_id = dt.id
           ) AS is_leaf
    FROM dept_tree dt
    ORDER BY dt.id
""")


def _row_to_dict(row) -> dict:
    """부서행 -> 응답 dict. is_leaf 면 JD 등록/이력서 업로드 가능."""
    is_leaf = bool(row.is_leaf)
    return {
        "id": row.id,
        "name": row.name,
        "parent_id": row.parent_id,
        "manager_id": row.manager_id,
        "email": row.email,
        "is_leaf": is_leaf,
        # 최하위 팀만 JD 등록/이력서 업로드 대상. 상위 조직은 조회만 가능.
        "can_register_jd": is_leaf,
        "can_upload_resume": is_leaf,
    }


def get_accessible_departments(db: Session, user: User) -> list:
    """
    현재 사용자가 접근 가능한 부서 목록(dict 리스트)을 반환합니다.
    - ADMIN: 전체 부서
    - MANAGER/VIEWER: department_id 기준 해당 부서 + 하위 부서 전체
    예외:
      - MANAGER/VIEWER 인데 department_id 가 없으면 400
      - department_id 가 departments 에 없으면 404
    """
    role = (user.role_code or "").upper()

    if role == "ADMIN":
        rows = db.execute(_ADMIN_SQL).fetchall()
        return [_row_to_dict(r) for r in rows]

    # MANAGER / VIEWER (TODO: VIEWER 는 향후 조회 전용 권한으로 세분화 예정. 현재는 MANAGER 와 동일)
    if not user.department_id:
        raise HTTPException(status_code=400, detail="담당 부서가 설정되지 않은 사용자입니다.")

    rows = db.execute(_SUBTREE_SQL, {"root": user.department_id}).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="담당 부서를 찾을 수 없습니다.")
    return [_row_to_dict(r) for r in rows]


# ----- JD 쓰기(등록/수정/삭제) 권한 검사 -----
# 부서 존재 + 최하위(leaf) 여부를 한 번에 확인합니다.
_EXISTS_LEAF_SQL = text(f"""
    SELECT
        EXISTS(SELECT 1 FROM {_SCHEMA}.departments d WHERE d.id = :d) AS dept_exists,
        NOT EXISTS(SELECT 1 FROM {_SCHEMA}.departments c WHERE c.parent_id = :d) AS is_leaf
""")

# MANAGER 의 권한 범위(:root + 하위 전체)에 :target 부서가 포함되는지 확인합니다. (recursive CTE)
_SUBTREE_CONTAINS_SQL = text(f"""
    WITH RECURSIVE dept_tree AS (
        SELECT id FROM {_SCHEMA}.departments WHERE id = :root
        UNION ALL
        SELECT child.id FROM {_SCHEMA}.departments child
        JOIN dept_tree parent ON child.parent_id = parent.id
    )
    SELECT EXISTS(SELECT 1 FROM dept_tree WHERE id = :target)
""")

# :root 부서 + 모든 하위 부서의 id 목록 (recursive CTE)
_SUBTREE_IDS_SQL = text(f"""
    WITH RECURSIVE dept_tree AS (
        SELECT id FROM {_SCHEMA}.departments WHERE id = :root
        UNION ALL
        SELECT child.id FROM {_SCHEMA}.departments child
        JOIN dept_tree parent ON child.parent_id = parent.id
    )
    SELECT id FROM dept_tree
""")


def get_accessible_department_ids(db: Session, user: User):
    """
    '조회'(이력서 현황 등) 권한 필터용 접근 가능 부서 id 목록을 반환합니다.
      - ADMIN            -> None (전체 허용 의미. department_id 무시)
      - MANAGER/VIEWER   -> 본인 department_id + 모든 하위 부서 id 리스트
    예외:
      - MANAGER/VIEWER 인데 department_id 가 없으면 400
      - department_id 가 departments 에 없으면 404
    (로그인 여부는 호출부의 get_current_user 의존성이 401 로 처리합니다.)
    """
    role = (user.role_code or "").upper()
    if role == "ADMIN":
        return None
    # MANAGER / VIEWER / 그 외(보수적으로 본인 부서 범위로 제한)
    if not user.department_id:
        raise HTTPException(status_code=400, detail="담당 부서가 설정되지 않은 사용자입니다.")
    rows = db.execute(_SUBTREE_IDS_SQL, {"root": user.department_id}).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="부서를 찾을 수 없습니다.")
    return [r.id for r in rows]


def _ensure_can_write_to_department(db: Session, user: User, department_id: str,
                                    *, leaf_required_msg: str, no_role_msg: str) -> None:
    """
    최하위 부서 쓰기(JD 등록/이력서 업로드 등) 공통 권한 검사. 권한 없으면 HTTPException.
    검사 순서(정책):
      1) department_id 가 departments 에 존재 (없으면 404)
      2) 대상 부서가 최하위(leaf) 부서 (상위 조직이면 400 — leaf_required_msg)
      3) ADMIN -> 통과 (department_id 무시)
      4) MANAGER -> 본인 department_id 기준 하위 부서(recursive)에 포함되어야 통과 (아니면 403)
      5) VIEWER / 알 수 없는 role -> 403 (no_role_msg)
    (로그인 여부 자체는 호출부의 get_current_user 의존성이 401 로 처리합니다.)
    """
    if not department_id:
        raise HTTPException(status_code=404, detail="부서를 찾을 수 없습니다.")

    info = db.execute(_EXISTS_LEAF_SQL, {"d": department_id}).first()
    if not info or not info.dept_exists:
        raise HTTPException(status_code=404, detail="부서를 찾을 수 없습니다.")
    if not info.is_leaf:
        raise HTTPException(status_code=400, detail=leaf_required_msg)

    role = (user.role_code or "").upper()
    if role == "ADMIN":
        return
    if role == "MANAGER":
        if not user.department_id:
            raise HTTPException(status_code=403, detail="해당 부서에 대한 권한이 없습니다.")
        in_scope = db.execute(
            _SUBTREE_CONTAINS_SQL, {"root": user.department_id, "target": department_id}
        ).scalar()
        if not in_scope:
            raise HTTPException(status_code=403, detail="해당 부서에 대한 권한이 없습니다.")
        return
    # VIEWER (TODO: 향후 조회 전용 권한으로 세분화 예정) 또는 알 수 없는 role
    raise HTTPException(status_code=403, detail=no_role_msg)


def ensure_can_manage_jd(db: Session, user: User, department_id: str) -> None:
    """JD 등록/수정/삭제 권한 검사. (최하위 부서만, ADMIN 전체 / MANAGER 본인 하위)"""
    _ensure_can_write_to_department(
        db, user, department_id,
        leaf_required_msg="JD는 최하위 부서/팀에만 등록할 수 있습니다.",
        no_role_msg="JD를 등록/수정할 권한이 없습니다.",
    )


def ensure_can_upload_resume(db: Session, user: User, department_id: str) -> None:
    """이력서 업로드 권한 검사. (최하위 부서만, ADMIN 전체 / MANAGER 본인 하위, VIEWER 불가)"""
    _ensure_can_write_to_department(
        db, user, department_id,
        leaf_required_msg="이력서는 최하위 부서/팀에만 업로드할 수 있습니다.",
        no_role_msg="이력서를 업로드할 권한이 없습니다.",
    )


def ensure_department_access(db: Session, user: User, department_id: str) -> None:
    """
    부서 단위 '조회' 접근 권한 검사. (분석 대기 파일 조회 등)
      - ADMIN            -> 통과 (department_id 무시)
      - MANAGER/VIEWER   -> department_id 가 본인 부서+하위(recursive)에 포함되어야 통과
    권한 없으면 403. (VIEWER 도 본인 범위 조회는 허용 — 실행과 달리 조회는 막지 않음)
    (최하위 부서 여부는 보지 않습니다. 상위 조직 조회는 허용)
    """
    role = (user.role_code or "").upper()
    if role == "ADMIN":
        return
    if not user.department_id:
        raise HTTPException(status_code=400, detail="담당 부서가 설정되지 않은 사용자입니다.")
    in_scope = db.execute(
        _SUBTREE_CONTAINS_SQL, {"root": user.department_id, "target": department_id}
    ).scalar()
    if not in_scope:
        raise HTTPException(status_code=403, detail="해당 부서에 대한 권한이 없습니다.")


def ensure_can_run_analysis(db: Session, user: User, department_id: str) -> None:
    """
    분석 실행 권한 검사. (선택 부서 분석 실행 등)
      - ADMIN            -> 통과 (department_id 무시)
      - MANAGER          -> department_id 가 본인 부서+하위(recursive)에 포함되어야 통과
      - VIEWER/알 수 없는 role -> 403 (분석 실행 불가)
    (최하위 부서 여부는 보지 않습니다 — 업로드된 파일이 있는 부서 기준 실행)
    """
    role = (user.role_code or "").upper()
    if role == "ADMIN":
        return
    if role == "MANAGER":
        if not user.department_id:
            raise HTTPException(status_code=403, detail="해당 부서의 분석 실행 권한이 없습니다.")
        in_scope = db.execute(
            _SUBTREE_CONTAINS_SQL, {"root": user.department_id, "target": department_id}
        ).scalar()
        if not in_scope:
            raise HTTPException(status_code=403, detail="해당 부서의 분석 실행 권한이 없습니다.")
        return
    # VIEWER / 알 수 없는 role
    raise HTTPException(status_code=403, detail="분석 실행 권한이 없습니다.")


def ensure_can_download_resume(db: Session, user: User, department_id: str) -> None:
    """
    이력서 원본 파일 다운로드 권한 검사.
      - ADMIN            -> 통과 (department_id 무시)
      - MANAGER          -> department_id 가 본인 부서+하위(recursive)에 포함되어야 통과
      - VIEWER/알 수 없는 role -> 403 (이번 단계 다운로드 불가)
    """
    role = (user.role_code or "").upper()
    if role == "ADMIN":
        return
    if role == "MANAGER":
        if not user.department_id:
            raise HTTPException(status_code=403, detail="파일을 다운로드할 권한이 없습니다.")
        in_scope = db.execute(
            _SUBTREE_CONTAINS_SQL, {"root": user.department_id, "target": department_id}
        ).scalar()
        if not in_scope:
            raise HTTPException(status_code=403, detail="파일을 다운로드할 권한이 없습니다.")
        return
    # VIEWER / 알 수 없는 role
    raise HTTPException(status_code=403, detail="파일을 다운로드할 권한이 없습니다.")


# ----- 부서 이름/경로(path) 및 검색 (사용자 관리 화면용) -----
def get_department_node_map(db: Session):
    """
    전체 부서를 {id: (name, parent_id)} 맵 + 부모로 참조되는 id 집합(parent_ids) 으로 반환합니다.
    parent_ids 에 없는 부서는 최하위(leaf). (사용자 목록/검색의 path/is_leaf 계산 공용)
    """
    rows = db.query(Department.id, Department.name, Department.parent_id).all()
    node = {r[0]: (r[1], r[2]) for r in rows}
    parent_ids = {r[2] for r in rows if r[2]}
    return node, parent_ids


def build_department_path(dept_id, node) -> str:
    """dept_id 의 상위 경로를 '전사 > ... > 부서명' 형태로 반환합니다. (없으면 '')"""
    parts, seen, cur = [], set(), dept_id
    while cur and cur in node and cur not in seen:
        seen.add(cur)
        name, parent = node[cur]
        parts.append(name)
        cur = parent
    return " > ".join(reversed(parts))


def department_name_and_path(db: Session, dept_id):
    """dept_id 의 (name, path) 를 반환합니다. dept_id 가 없거나 미존재면 (None, None)."""
    if not dept_id:
        return None, None
    node, _ = get_department_node_map(db)
    if dept_id not in node:
        return None, None
    return node[dept_id][0], build_department_path(dept_id, node)


def department_exists(db: Session, dept_id: str) -> bool:
    """departments.id 존재 여부."""
    return db.query(Department.id).filter(Department.id == dept_id).first() is not None


def subtree_department_ids(db: Session, root_id: str) -> list:
    """root_id 부서와 그 하위 부서 id 전부를 반환합니다. (상위 부서 선택 시 하위 포함 조회용)"""
    rows = db.execute(_SUBTREE_IDS_SQL, {"root": root_id}).fetchall()
    return [r.id for r in rows]


def search_departments(db: Session, keyword: str, limit: int = 30) -> list:
    """
    부서/팀을 id 또는 name 부분일치로 검색합니다. (사용자 추가/수정의 부서 선택용)
    - keyword 가 비었거나 1글자면 상위 limit 개를 정렬해 반환합니다.
    - 최하위 부서로 제한하지 않습니다. (MANAGER 가 상위 조직 담당일 수 있음)
    반환: [{id, name, parent_id, path, is_leaf}]
    """
    node, parent_ids = get_department_node_map(db)
    kw = (keyword or "").strip()
    q = db.query(Department.id, Department.name, Department.parent_id)
    if len(kw) >= 2:
        like = f"%{kw}%"
        q = q.filter(or_(Department.id.ilike(like), Department.name.ilike(like)))
    rows = q.order_by(Department.name).limit(limit).all()
    return [
        {
            "id": r[0],
            "name": r[1],
            "parent_id": r[2],
            "path": build_department_path(r[0], node),
            "is_leaf": r[0] not in parent_ids,
        }
        for r in rows
    ]


def search_accessible_departments(db: Session, user: User, keyword: str, limit: int = 30) -> list:
    """
    로그인 사용자의 '권한 범위 내' 부서/팀을 검색합니다. (공고 등록 부서 선택용 — 사용자 관리의 검색 UI와 동일 응답 모양)
    - ADMIN: 전체 부서에서 검색 (search_departments 와 동일)
    - MANAGER/VIEWER: 본인 부서 + 하위 부서로만 제한 (권한 밖 부서는 검색 결과에 노출되지 않음)
    반환: [{id, name, parent_id, path, is_leaf}]  (사용자 관리 부서검색과 동일 스키마)
    """
    allowed = get_accessible_department_ids(db, user)  # ADMIN -> None(전체), 그 외 -> 부서 id 리스트
    results = search_departments(db, keyword, limit=(limit if allowed is None else 1000))
    if allowed is None:
        return results[:limit]
    allowed_set = set(allowed)
    return [r for r in results if r["id"] in allowed_set][:limit]
