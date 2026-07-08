from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models.job_posting import JobPosting
from app.db.models.job_posting_jd import JobPostingJD
from app.services import department_access_service as das

# 공고/JD 관리 서비스. resume_ai.job_postings / job_posting_jds 만 다룹니다.
# 권한:
#   - 조회: ADMIN 전체 / MANAGER·VIEWER 본인 부서+하위 (das.ensure_department_access)
#   - 등록/수정(공고/JD/상태): ADMIN 전체 / MANAGER 본인 부서+하위 / VIEWER 불가 (_ensure_can_manage)
# 현재 1공고 = 1 active JD (DB unique 없이 여기서 강제).

PLATFORM_LABEL = {
    "SARAMIN": "사람인", "JOBKOREA": "잡코리아", "WANTED": "원티드", "ETC": "기타",
}
VALID_STATUS = {"DRAFT", "OPEN", "CLOSED", "INACTIVE"}
VALID_PLATFORM = set(PLATFORM_LABEL.keys())

# JD 분석 파이프라인(사람인 배치 → Celery worker) 전용 상태값.
# 사용자 편집용 VALID_STATUS 와 분리합니다: 같은 job_postings.status(varchar) 컬럼에 기록하되,
# 수동 공고 등록/수정 검증(_validate_posting_fields / set_status)에는 넣지 않습니다(UI 상태 목록 불변).
JD_LIFECYCLE_STATUS = {"JD_QUEUED", "JD_PROCESSING", "JD_READY", "JD_FAILED"}


# ----- 권한 -----
def _ensure_can_manage(db: Session, user, department_id) -> None:
    """공고/JD 등록·수정 권한. VIEWER/기타 403, MANAGER 는 본인 부서+하위만.
    department_id 가 비어 있으면(부서 미지정 공고) 부서 범위 검사는 생략하고 역할만 검사합니다."""
    role = (user.role_code or "").upper()
    if role not in ("ADMIN", "MANAGER"):
        raise HTTPException(status_code=403, detail="공고를 등록/수정할 권한이 없습니다.")
    if role == "ADMIN":
        return
    if not department_id:
        return  # 부서 미지정: MANAGER 도 역할 검사만 통과(부서 범위 검사 생략)
    allowed = das.get_accessible_department_ids(db, user)  # MANAGER -> 부서 id 리스트
    if allowed is not None and department_id not in allowed:
        raise HTTPException(status_code=403, detail="해당 부서의 공고를 관리할 권한이 없습니다.")


def _ensure_can_read(db: Session, user, department_id: str) -> None:
    """공고 조회 권한. ADMIN 전체 / MANAGER·VIEWER 본인 부서+하위 (권한 밖 403)."""
    das.ensure_department_access(db, user, department_id)


# ----- 변환 -----
def _active_jd(db: Session, posting_id: int):
    return (
        db.query(JobPostingJD)
        .filter(JobPostingJD.posting_id == posting_id, JobPostingJD.is_active.is_(True))
        .order_by(JobPostingJD.id.desc())
        .first()
    )


def _posting_dict(p: JobPosting, node: dict, has_jd: bool) -> dict:
    dept_name = node[p.department_id][0] if (p.department_id and p.department_id in node) else None
    dept_path = das.build_department_path(p.department_id, node) if (p.department_id and p.department_id in node) else None
    return {
        "id": p.id,
        "title": p.title,
        "department_id": p.department_id,
        "department_name": dept_name,
        "department_path": dept_path,
        "platform_code": p.platform_code,
        "platform_label": PLATFORM_LABEL.get(p.platform_code) if p.platform_code else None,
        "platform_posting_url": p.platform_posting_url,
        "status": p.status,
        "has_jd": has_jd,
        "jd_status": "JD 등록 완료" if has_jd else "JD 미등록",
        "created_by": p.created_by,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


def _jd_dict(jd: JobPostingJD) -> dict:
    return {
        "id": jd.id,
        "posting_id": jd.posting_id,
        "title": jd.title,
        "required_skills": jd.required_skills or [],
        "preferred_skills": jd.preferred_skills or [],
        "jd_content": jd.jd_content,
        "is_active": jd.is_active,
        "created_at": jd.created_at,
        "updated_at": jd.updated_at,
    }


def _auto_platform_code(platform_code, url):
    """platform_code 미지정 시 공고 URL 도메인으로 자동 매핑(SARAMIN/JOBKOREA 등).

    - 이미 platform_code 가 있으면 사용자가 고른 값을 그대로 존중합니다(덮어쓰지 않음).
    - URL 도메인이 지원 플랫폼(VALID_PLATFORM)으로 매핑될 때만 채웁니다. 그 외(점핏 등 미지원/알 수 없는
      도메인)는 기존 기본값(None)을 유지합니다 — platform_code 가 null 로 들어가도 오류를 내지 않습니다.
    """
    if platform_code or not url:
        return platform_code
    from app.services import job_extract_service   # lazy: import-time 순환 방지
    derived = job_extract_service.platform_code_for_url(url)
    return derived if derived in VALID_PLATFORM else platform_code


def _validate_posting_fields(db: Session, department_id, platform_code, status):
    if platform_code and platform_code not in VALID_PLATFORM:
        raise HTTPException(status_code=400, detail="플랫폼 값이 올바르지 않습니다.")
    if status and status not in VALID_STATUS:
        raise HTTPException(status_code=400, detail="공고 상태 값이 올바르지 않습니다.")
    if department_id and not das.department_exists(db, department_id):
        raise HTTPException(status_code=404, detail="부서를 찾을 수 없습니다.")


# ----- 목록/상세 -----
def list_postings(db: Session, user, keyword=None, department_id=None,
                  platform_code=None, status=None, jd_status=None,
                  date_from=None, date_to=None, page=None, size=None) -> list:
    """권한 범위 내 공고 목록(필터 적용). 모든 필터는 백엔드에서 적용합니다.

    date_from/date_to: 등록일(created_at) 범위(YYYY-MM-DD). date_to 는 해당 일자까지 포함.
    jd_status: ALL(전체) / REGISTERED(JD 등록 완료) / NOT_REGISTERED(미등록). (NONE 은 하위호환)
    department_id: 해당 부서 + 하위 부서(subtree) 공고만. 권한 밖이면 403.
    page/size 가 주어지면 {"items", "total", "page", "size"} dict 를, 없으면 list 를 반환합니다.
    """
    allowed = das.get_accessible_department_ids(db, user)  # ADMIN None, else list
    q = db.query(JobPosting)
    if allowed is not None:
        if not allowed:
            return {"items": [], "total": 0, "page": page or 1, "size": size or 20} if page else []
        q = q.filter(JobPosting.department_id.in_(allowed))
    if department_id:
        # 상위 부서 선택 시 하위 부서 공고까지. 권한 밖 부서 요청은 403.
        das.ensure_department_access(db, user, department_id)
        q = q.filter(JobPosting.department_id.in_(das.subtree_department_ids(db, department_id)))
    if platform_code:
        q = q.filter(JobPosting.platform_code == platform_code)
    if status:
        q = q.filter(JobPosting.status == status)
    if date_from:
        try:
            q = q.filter(JobPosting.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            raise HTTPException(status_code=400, detail="등록일 시작 형식이 올바르지 않습니다(YYYY-MM-DD).")
    if date_to:
        try:
            end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            q = q.filter(JobPosting.created_at < end)
        except ValueError:
            raise HTTPException(status_code=400, detail="등록일 종료 형식이 올바르지 않습니다(YYYY-MM-DD).")
    kw = (keyword or "").strip()
    if kw:
        q = q.filter(JobPosting.title.ilike(f"%{kw}%"))
    postings = q.order_by(JobPosting.created_at.desc(), JobPosting.id.desc()).all()

    # 활성 JD 보유 공고 id 집합 (N+1 방지)
    ids = [p.id for p in postings]
    jd_posting_ids = set()
    if ids:
        rows = (db.query(JobPostingJD.posting_id)
                .filter(JobPostingJD.posting_id.in_(ids), JobPostingJD.is_active.is_(True))
                .all())
        jd_posting_ids = {r[0] for r in rows}

    node, _ = das.get_department_node_map(db)
    out = [_posting_dict(p, node, p.id in jd_posting_ids) for p in postings]
    js = (jd_status or "").upper()
    if js == "REGISTERED":
        out = [o for o in out if o["has_jd"]]
    elif js in ("NOT_REGISTERED", "NONE"):
        out = [o for o in out if not o["has_jd"]]

    if page is None:
        return out   # 페이징 미지정(검색 선택용 등) → 전체 리스트
    page = max(1, int(page))
    size = max(1, min(int(size or 20), 200))
    total = len(out)
    start = (page - 1) * size
    return {"items": out[start:start + size], "total": total, "page": page, "size": size}


def get_posting(db: Session, user, posting_id: int) -> dict:
    p = db.query(JobPosting).filter(JobPosting.id == posting_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="공고를 찾을 수 없습니다.")
    _ensure_can_read(db, user, p.department_id)
    node, _ = das.get_department_node_map(db)
    has_jd = _active_jd(db, posting_id) is not None
    return _posting_dict(p, node, has_jd)


def search_postings(db: Session, user, keyword=None, limit: int = 30) -> list:
    """이력서 등록/분석/현황의 공고 선택용 경량 검색. (권한 범위 내, JD 등록 여부 포함)"""
    return list_postings(db, user, keyword=keyword)[:limit]


# ----- 등록/수정/상태 -----
def create_posting(db: Session, user, data) -> dict:
    """공고 등록(DB 만). 부서/팀은 선택사항(미지정 가능). Drive 공고 폴더는 'JD 등록 완료 시점'에 생성합니다(upsert_jd 참고)."""
    title = (data.title or "").strip()
    dept_id = (data.department_id or "").strip() or None   # 빈 값이면 부서 미지정(None)
    if not title:
        raise HTTPException(status_code=400, detail="공고명은 필수입니다.")
    _ensure_can_manage(db, user, dept_id)
    _validate_posting_fields(db, dept_id, data.platform_code, data.status)
    now = datetime.now()
    url = (data.platform_posting_url or "").strip() or None
    platform_code = _auto_platform_code((data.platform_code or "").strip() or None, url)
    p = JobPosting(
        title=title, department_id=dept_id,
        platform_code=platform_code,
        platform_posting_url=url,
        status=(data.status or "OPEN"),
        created_by=user.id, updated_at=now,
    )
    try:
        db.add(p)
        db.commit()
        db.refresh(p)
    except Exception:
        db.rollback()
        raise
    node, _ = das.get_department_node_map(db)
    return _posting_dict(p, node, has_jd=False)


# ----- 이력서 업로드/분석 연동용 헬퍼 -----
def get_posting_entity(db: Session, posting_id: int) -> JobPosting:
    """공고 ORM 엔티티 (없으면 404)."""
    p = db.query(JobPosting).filter(JobPosting.id == posting_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="공고를 찾을 수 없습니다.")
    return p


def ensure_can_manage_posting(db: Session, user, posting: JobPosting) -> None:
    """공고에 대한 등록/수정/업로드/분석 실행 권한(VIEWER 403, MANAGER 본인 부서+하위)."""
    _ensure_can_manage(db, user, posting.department_id)


def get_active_jd_entity(db: Session, posting_id: int):
    """공고의 현재 active JD ORM (없으면 None)."""
    return _active_jd(db, posting_id)


def mark_jd_lifecycle_status(db: Session, posting_id: int, status: str) -> None:
    """JD 분석 파이프라인(사람인 배치 → Celery worker) 전용 상태 기록.

    권한 검사/사용자 검증(VALID_STATUS) 없이 내부(배치/worker)에서만 호출합니다.
    JD_LIFECYCLE_STATUS 값만 허용합니다. 공고가 없으면 조용히 무시합니다(worker 재시도 안전).
    """
    if status not in JD_LIFECYCLE_STATUS:
        raise ValueError(f"invalid jd lifecycle status: {status}")
    p = db.query(JobPosting).filter(JobPosting.id == posting_id).first()
    if not p:
        return
    p.status = status
    p.updated_at = datetime.now()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def posting_dept_name(db: Session, posting: JobPosting) -> str:
    """공고 부서명(추천 JD 프롬프트용). 없으면 department_id 그대로."""
    node, _ = das.get_department_node_map(db)
    if posting.department_id and posting.department_id in node:
        return node[posting.department_id][0]
    return posting.department_id or ""


def update_posting(db: Session, user, posting_id: int, data) -> dict:
    p = db.query(JobPosting).filter(JobPosting.id == posting_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="공고를 찾을 수 없습니다.")
    # 현재 부서 기준 권한
    _ensure_can_manage(db, user, p.department_id)
    fields = data.model_dump(exclude_unset=True)
    # 부서/팀은 선택사항: 빈 값이면 미지정(None)으로 변경 가능
    if "department_id" in fields:
        new_dept = (fields["department_id"] or "").strip() or None
    else:
        new_dept = p.department_id
    # 부서 변경 시 새 부서도 권한·존재 검증
    if new_dept != p.department_id:
        _ensure_can_manage(db, user, new_dept)
    _validate_posting_fields(db, new_dept, fields.get("platform_code"), fields.get("status"))

    if "title" in fields and fields["title"]:
        p.title = fields["title"].strip()
    if "department_id" in fields:
        p.department_id = new_dept   # None(미지정) 가능
    if "platform_code" in fields:
        p.platform_code = fields["platform_code"] or None
    if "platform_posting_url" in fields:
        p.platform_posting_url = fields["platform_posting_url"] or None
    # platform_code 가 비어 있고 URL 이 있으면 도메인으로 자동 매핑(사용자가 고른 값은 덮지 않음)
    p.platform_code = _auto_platform_code(p.platform_code, (p.platform_posting_url or "").strip() or None)
    if "status" in fields and fields["status"]:
        p.status = fields["status"]
    p.updated_at = datetime.now()
    try:
        db.commit()
        db.refresh(p)
    except Exception:
        db.rollback()
        raise
    node, _ = das.get_department_node_map(db)
    return _posting_dict(p, node, _active_jd(db, posting_id) is not None)


def set_status(db: Session, user, posting_id: int, status: str) -> dict:
    p = db.query(JobPosting).filter(JobPosting.id == posting_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="공고를 찾을 수 없습니다.")
    _ensure_can_manage(db, user, p.department_id)
    if status not in VALID_STATUS:
        raise HTTPException(status_code=400, detail="공고 상태 값이 올바르지 않습니다.")
    p.status = status
    p.updated_at = datetime.now()
    try:
        db.commit()
        db.refresh(p)
    except Exception:
        db.rollback()
        raise
    node, _ = das.get_department_node_map(db)
    return _posting_dict(p, node, _active_jd(db, posting_id) is not None)


# ----- JD -----
def get_jd(db: Session, user, posting_id: int):
    """공고의 현재 active JD (없으면 None). 조회 권한 검증."""
    p = db.query(JobPosting).filter(JobPosting.id == posting_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="공고를 찾을 수 없습니다.")
    _ensure_can_read(db, user, p.department_id)
    jd = _active_jd(db, posting_id)
    return _jd_dict(jd) if jd else None


def upsert_jd(db: Session, user, posting_id: int, data, drive_factory=None) -> dict:
    """공고 JD 등록/수정. 기존 active JD 는 비활성화하고 새 active JD 1건을 만듭니다.

    JD 저장 시점에 공고 Drive 폴더(inbox/completed/failed 아래 공고명 폴더)를 생성합니다.
      - 이미 폴더 id 가 있으면 재생성하지 않습니다(멱등).
      - drive_factory: 인증된 GoogleDriveService 를 반환하는 콜러블(폴더가 없을 때만 호출).
      - JD 저장 + Drive 폴더 생성은 한 트랜잭션 — Drive 생성 실패 시 JD 저장도 롤백합니다.
    """
    p = db.query(JobPosting).filter(JobPosting.id == posting_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="공고를 찾을 수 없습니다.")
    _ensure_can_manage(db, user, p.department_id)
    title = (data.title or "").strip() or p.title  # 기본값=공고명
    now = datetime.now()
    need_folders = not p.drive_inbox_folder_id   # inbox 가 없으면 미생성 상태로 간주
    try:
        # 기존 active JD 전부 비활성화 (1 active 강제)
        db.query(JobPostingJD).filter(
            JobPostingJD.posting_id == posting_id, JobPostingJD.is_active.is_(True)
        ).update({JobPostingJD.is_active: False, JobPostingJD.updated_at: now},
                 synchronize_session=False)
        jd = JobPostingJD(
            posting_id=posting_id, title=title,
            required_skills=data.required_skills or [],
            preferred_skills=data.preferred_skills or [],
            jd_content=data.jd_content or None,
            is_active=True, created_by=user.id, updated_at=now,
        )
        db.add(jd)
        # Drive 공고 폴더 생성(없을 때만). 같은 트랜잭션이라 실패 시 JD 저장도 롤백.
        if need_folders and drive_factory is not None:
            from app.services import job_posting_drive_service
            drive = drive_factory()
            folders = job_posting_drive_service.ensure_posting_folders(drive, p.id, p.title)
            p.drive_folder_id = folders["drive_folder_id"]
            p.drive_inbox_folder_id = folders["inbox"]
            p.drive_completed_folder_id = folders["completed"]
            p.drive_failed_folder_id = folders["failed"]
            p.updated_at = now
        db.commit()
        db.refresh(jd)
    except Exception:
        db.rollback()
        raise
    return _jd_dict(jd)
