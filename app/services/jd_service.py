from pathlib import Path
from typing import List

from app.schemas.jd_schema import JD, JDSaveRequest
from app.services.dept_service import DeptService
from app.services import jd_db_service

# LEGACY: 부서(팀) 기준 JD 서비스(legacy job_descriptions 테이블). 공고 중심 전환으로 신규 개발 대상이 아닙니다.
#         신규 JD 는 공고별 job_posting_jds(job_posting_service.upsert_jd)를 사용하세요.
#         (jd_router / analyze_router / resume_analysis_service.analyze_pending(legacy) 에서만 사용.
#          동작 변경 금지, 후속 제거 검토 — docs/TODO.)
#
# JDService 는 "팀별 JD 1건" 을 조회/저장하는 서비스입니다.
#
# 기준 저장소가 로컬 JSON 에서 **DB(resume_ai.job_descriptions)** 로 전환되었습니다.
# 라우터/화면(JD 등록 화면)은 그대로 두고, 이 클래스 내부 저장소만 DB 로 바꿉니다.
#
# 매핑: JD.position_title <-> title, JD.job_description <-> description.
#       (job_descriptions 테이블에는 manager_email 컬럼이 없어 저장하지 않습니다.)

# (구) 로컬 JSON 경로. 이제 기준 저장소가 아니며, 호환을 위해 상수만 남겨둡니다.
JD_DIR = Path("data/config/jd")


def parse_skill_text(text: str) -> List[str]:
    """
    화면 textarea 로 받은 기술 스택 문자열을 리스트로 변환합니다.
    콤마(,) 또는 줄바꿈(\\n) 어느 쪽으로 구분해도 동작합니다.
    빈 항목과 앞뒤 공백은 제거합니다.

    예: "Java, Spring\\nRedis" -> ["Java", "Spring", "Redis"]
    """
    normalized = text.replace("\n", ",")
    return [token.strip() for token in normalized.split(",") if token.strip()]


def _jd_from_active(dept_id: str, active: dict, dept_name: str) -> JD:
    return JD(
        dept_id=dept_id,
        dept_name=dept_name,
        position_title=active["title"] or "",
        job_description=active["description"] or "",
        required_skills=active["required_skills"] or [],
        preferred_skills=active["preferred_skills"] or [],
        min_years=active["min_years"] or 0,
        manager_email="",  # DB 테이블에 컬럼 없음
        version=active["version"],
        update_date=active["updated_at"] or active["created_at"],
    )


class JDService:
    def __init__(self):
        # 부서명 표시용 (화면 표시값일 뿐, JD 저장 기준은 dept_id)
        self.dept_service = DeptService()

    def _dept_name(self, dept_id: str) -> str:
        dept = self.dept_service.get_by_id(dept_id)
        return dept.name if dept else ""

    def get(self, dept_id: str) -> JD:
        """
        팀의 active JD 를 DB 에서 조회합니다.
        저장된 active JD 가 없으면 기본 JD 템플릿(version 0)을 반환합니다.
        """
        active = jd_db_service.get_active(dept_id)
        if active:
            return _jd_from_active(dept_id, active, self._dept_name(dept_id))
        return self._default_template(dept_id)

    def save(self, dept_id: str, req: JDSaveRequest) -> JD:
        """
        팀의 JD 를 DB(job_descriptions)에 새 active 버전으로 저장합니다.
        (기존 active 는 비활성화하고 version 을 1 올립니다.)
        """
        created = jd_db_service.create(
            dept_id=dept_id,
            title=req.position_title,
            description=req.job_description,
            required_skills=parse_skill_text(req.required_skills),
            preferred_skills=parse_skill_text(req.preferred_skills),
            min_years=req.min_years,
        )
        return _jd_from_active(dept_id, created, self._dept_name(dept_id))

    def _default_template(self, dept_id: str) -> JD:
        """저장된 JD 가 없을 때 보여줄 기본 템플릿. (version 0 = 미등록)"""
        dept = self.dept_service.get_by_id(dept_id)
        dept_name = dept.name if dept else ""
        manager_email = dept.email if (dept and dept.email) else ""
        return JD(
            dept_id=dept_id,
            dept_name=dept_name,
            position_title=f"{dept_name} 채용 포지션",
            job_description="이 팀의 직무 내용을 입력하세요.",
            required_skills=[],
            preferred_skills=[],
            min_years=0,
            manager_email=manager_email,
            version=0,
            update_date=None,
        )
