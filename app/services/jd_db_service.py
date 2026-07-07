from datetime import datetime

from sqlalchemy import func

from app.db.session import SessionLocal
from app.db.models.job_description import JobDescription

# LEGACY: legacy job_descriptions(부서별 JD) 테이블 전용 서비스. 공고 중심 전환으로 신규 개발 대상이 아닙니다.
#         신규 JD 는 공고별 job_posting_jds 를 사용하세요. job_descriptions 에 신규 작성 금지.
#         (jds_router / jd_service / resume_analysis_service.analyze_pending(legacy) 에서만 사용.
#          동작 변경 금지, 후속 제거 검토 — docs/TODO.)
#
# jd_db_service 는 resume_ai.job_descriptions 테이블만 다룹니다.
# 정책(MVP): dept_id 당 active JD 1개. 새 JD 등록 시 기존 active 를 false 로 내리고 새 버전을 active 로.
# 물리 삭제보다 is_active=false(soft delete) 우선.


def _to_dict(r: JobDescription) -> dict:
    return {
        "id": r.id,
        "dept_id": r.dept_id,
        "title": r.title,
        "description": r.description,
        "required_skills": r.required_skills or [],
        "preferred_skills": r.preferred_skills or [],
        "min_years": r.min_years,
        "version": r.version,
        "is_active": r.is_active,
        "created_at": r.created_at.isoformat(timespec="seconds") if r.created_at else None,
        "updated_at": r.updated_at.isoformat(timespec="seconds") if r.updated_at else None,
    }


def list_by_dept(dept_id: str) -> list:
    """부서의 JD 전체(버전 포함)를 최신순으로 반환합니다."""
    session = SessionLocal()
    try:
        rows = (
            session.query(JobDescription)
            .filter(JobDescription.dept_id == dept_id)
            .order_by(JobDescription.version.desc())
            .all()
        )
        return [_to_dict(r) for r in rows]
    finally:
        session.close()


def get_by_id(jd_id: int) -> dict:
    """JD 1건을 id 로 조회합니다. 없으면 None. (수정/삭제 권한 체크용 dept_id 확인 등)"""
    session = SessionLocal()
    try:
        r = session.query(JobDescription).filter(JobDescription.id == jd_id).first()
        return _to_dict(r) if r else None
    finally:
        session.close()


def get_active(dept_id: str) -> dict:
    """부서의 현재 active JD 1건을 반환합니다. 없으면 None."""
    session = SessionLocal()
    try:
        r = (
            session.query(JobDescription)
            .filter(JobDescription.dept_id == dept_id, JobDescription.is_active.is_(True))
            .order_by(JobDescription.version.desc())
            .first()
        )
        return _to_dict(r) if r else None
    finally:
        session.close()


def create(dept_id: str, title, description, required_skills, preferred_skills,
           min_years) -> dict:
    """
    부서의 새 active JD 를 등록합니다. (기존 active 는 is_active=false 로 내림)
    version 은 부서 내 최대 version+1. 트랜잭션, 실패 시 rollback.
    """
    session = SessionLocal()
    try:
        session.query(JobDescription).filter(
            JobDescription.dept_id == dept_id, JobDescription.is_active.is_(True)
        ).update({JobDescription.is_active: False}, synchronize_session=False)

        max_version = session.query(func.max(JobDescription.version)).filter(
            JobDescription.dept_id == dept_id
        ).scalar() or 0

        jd = JobDescription(
            dept_id=dept_id, title=title, description=description,
            required_skills=required_skills or [], preferred_skills=preferred_skills or [],
            min_years=min_years,
            version=max_version + 1, is_active=True,
        )
        session.add(jd)
        session.commit()
        session.refresh(jd)
        return _to_dict(jd)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def update(jd_id: int, fields: dict) -> dict:
    """JD 1건을 수정합니다. 없으면 None."""
    allowed = {"title", "description", "required_skills", "preferred_skills",
               "min_years", "is_active"}
    session = SessionLocal()
    try:
        jd = session.query(JobDescription).filter(JobDescription.id == jd_id).first()
        if not jd:
            return None
        for k, v in fields.items():
            if k in allowed and v is not None:
                setattr(jd, k, v)
        jd.updated_at = datetime.now()
        session.commit()
        session.refresh(jd)
        return _to_dict(jd)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def deactivate(jd_id: int) -> bool:
    """JD 1건을 soft delete(is_active=false) 합니다. 대상이 없으면 False."""
    session = SessionLocal()
    try:
        jd = session.query(JobDescription).filter(JobDescription.id == jd_id).first()
        if not jd:
            return False
        jd.is_active = False
        jd.updated_at = datetime.now()
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# status_by_department(부서별 JD 등록 현황)은 공고/JD 중심 전환으로
# 'Drive 설정/동기화 > job_descriptions 카드' 팝업과 함께 제거되었습니다.
