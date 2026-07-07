from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models.user import User
from app.core.password import hash_password, generate_temporary_password
from app.services import department_access_service as dept_svc

# 관리자 > 사용자 관리(resume_ai.users) 서비스입니다.
# 보안 주의: password_hash 는 어떤 반환값에도 포함하지 않습니다. (응답 dict 에 미포함)

VALID_ROLES = {"ADMIN", "MANAGER", "VIEWER"}
# MANAGER/VIEWER 는 department_id 필수, ADMIN 은 선택(NULL 가능)
DEPT_REQUIRED_ROLES = {"MANAGER", "VIEWER"}


def _to_dict(user: User, node: dict) -> dict:
    """User -> 응답 dict (부서 name/path 포함, password_hash 제외)."""
    dept_id = user.department_id
    dept_name = node[dept_id][0] if dept_id and dept_id in node else None
    dept_path = dept_svc.build_department_path(dept_id, node) if dept_id and dept_id in node else None
    return {
        "id": user.id,
        "login_id": user.login_id,
        "email": user.email,
        "name": user.name,
        "role_code": user.role_code,
        "department_id": dept_id,
        "department_name": dept_name,
        "department_path": dept_path,
        "is_active": user.is_active,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def _count_active_admins(db: Session) -> int:
    return (
        db.query(User)
        .filter(User.role_code == "ADMIN", User.is_active.is_(True))
        .count()
    )


def _is_last_active_admin(db: Session, user: User) -> bool:
    """user 가 '마지막 활성 ADMIN' 인지 여부."""
    return (
        (user.role_code or "").upper() == "ADMIN"
        and user.is_active
        and _count_active_admins(db) <= 1
    )


def _validate_role_and_dept(db: Session, role_code: str, department_id):
    """role_code 유효성 + 부서 필수/존재 검증."""
    role = (role_code or "").upper()
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="role_code 는 ADMIN/MANAGER/VIEWER 중 하나여야 합니다.")
    if role in DEPT_REQUIRED_ROLES and not department_id:
        raise HTTPException(status_code=400, detail="MANAGER/VIEWER 는 담당 부서가 필요합니다.")
    if department_id and not dept_svc.department_exists(db, department_id):
        raise HTTPException(status_code=404, detail="부서를 찾을 수 없습니다.")


def list_users(db: Session) -> list:
    node, _ = dept_svc.get_department_node_map(db)
    users = db.query(User).order_by(User.id.asc()).all()
    return [_to_dict(u, node) for u in users]


def get_user(db: Session, user_id: int) -> dict | None:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    node, _ = dept_svc.get_department_node_map(db)
    return _to_dict(user, node)


def create_user(db: Session, data) -> tuple:
    """사용자 생성. 반환: (user_dict, temporary_password)."""
    login_id = (data.login_id or "").strip()
    email = (data.email or "").strip()
    name = (data.name or "").strip()
    role = (data.role_code or "").upper()
    dept_id = data.department_id or None

    if not login_id or not email or not name:
        raise HTTPException(status_code=400, detail="login_id, email, name 은 필수입니다.")
    if db.query(User).filter(User.login_id == login_id).first():
        raise HTTPException(status_code=400, detail="이미 사용 중인 login_id 입니다.")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="이미 사용 중인 email 입니다.")
    _validate_role_and_dept(db, role, dept_id)

    temp_password = generate_temporary_password()
    now = datetime.now()
    user = User(
        login_id=login_id, email=email, name=name, role_code=role,
        department_id=dept_id, is_active=True,
        password_hash=hash_password(temp_password),
        # users.updated_at 은 NOT NULL 이며 TimestampMixin 은 insert 기본값이 없어 명시 지정합니다.
        updated_at=now,
    )
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise
    node, _ = dept_svc.get_department_node_map(db)
    return _to_dict(user, node), temp_password


def update_user(db: Session, user_id: int, data, current_user: User) -> dict:
    """사용자 수정. login_id/password_hash 는 변경하지 않습니다."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    fields = data.model_dump(exclude_unset=True)
    new_role = (fields.get("role_code") if "role_code" in fields else user.role_code) or user.role_code
    new_role = new_role.upper()
    new_dept = fields["department_id"] if "department_id" in fields else user.department_id
    new_active = fields["is_active"] if "is_active" in fields else user.is_active

    # role/부서 검증
    _validate_role_and_dept(db, new_role, new_dept)

    # email 중복 (본인 제외)
    if "email" in fields and fields["email"]:
        dup = db.query(User).filter(
            User.email == fields["email"].strip(), User.id != user_id
        ).first()
        if dup:
            raise HTTPException(status_code=400, detail="이미 사용 중인 email 입니다.")

    # 마지막 활성 ADMIN 보호: role 강등 또는 비활성화 차단
    if _is_last_active_admin(db, user):
        if new_role != "ADMIN":
            raise HTTPException(status_code=400, detail="마지막 활성 ADMIN 계정의 역할은 변경할 수 없습니다.")
        if new_active is False:
            raise HTTPException(status_code=400, detail="마지막 활성 ADMIN 계정은 비활성화할 수 없습니다.")
    # 본인 계정 비활성화 차단
    if new_active is False and user_id == current_user.id:
        raise HTTPException(status_code=400, detail="본인 계정은 비활성화할 수 없습니다.")

    if "email" in fields and fields["email"]:
        user.email = fields["email"].strip()
    if "name" in fields and fields["name"]:
        user.name = fields["name"].strip()
    if "role_code" in fields:
        user.role_code = new_role
    if "department_id" in fields:
        user.department_id = new_dept
    if "is_active" in fields and fields["is_active"] is not None:
        user.is_active = fields["is_active"]
    user.updated_at = datetime.now()
    try:
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise
    node, _ = dept_svc.get_department_node_map(db)
    return _to_dict(user, node)


def set_active(db: Session, user_id: int, active: bool, current_user: User) -> dict:
    """사용자 활성/비활성 전환. 비활성화 시 본인/마지막 ADMIN 보호."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    if not active:
        if user_id == current_user.id:
            raise HTTPException(status_code=400, detail="본인 계정은 비활성화할 수 없습니다.")
        if _is_last_active_admin(db, user):
            raise HTTPException(status_code=400, detail="마지막 활성 ADMIN 계정은 비활성화할 수 없습니다.")
    user.is_active = active
    user.updated_at = datetime.now()
    try:
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise
    node, _ = dept_svc.get_department_node_map(db)
    return _to_dict(user, node)


def reset_password(db: Session, user_id: int) -> tuple:
    """비밀번호를 임시 비밀번호로 초기화. 반환: (login_id, temporary_password)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    temp_password = generate_temporary_password()
    user.password_hash = hash_password(temp_password)
    user.updated_at = datetime.now()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return user.login_id, temp_password
