from typing import List, Optional
from app.schemas.dept_schema import Dept
from app.data.dummy_dept_loader import load_depts

# LEGACY: 더미 JSON 부서 목록 서비스(dept_router 전용). 공고 중심 전환으로 신규 개발 대상이 아닙니다.
#         부서 조회는 department_access_service / department_db_service(DB 기준)를 사용하세요.
#         (동작 변경 금지, 후속 제거 검토 — docs/TODO.)
#
# DeptService 는 부서 목록을 제공하는 서비스입니다. (Spring 의 @Service 와 동일 역할)
#
# 지금은 부서 JSON 파일(data/dummy/departments.sample.json)을 읽어서 돌려주지만,
# 나중에 이 클래스 내부만 조직도 API 호출로 바꾸면
# 라우터/화면은 손대지 않아도 되도록 분리해 두었습니다.

class DeptService:
    def __init__(self):
        # JSON 로더에서 부서 목록을 읽어옵니다. (나중에 여기만 API 호출로 교체)
        self._depts = load_depts()

    def get_all(self) -> List[Dept]:
        """전체 부서 목록을 flat list 로 반환합니다. (트리 변환은 화면에서 처리)"""
        return self._depts

    def get_by_id(self, dept_id: str) -> Optional[Dept]:
        """부서 ID 로 1건 조회. 없으면 None."""
        for dept in self._depts:
            if dept.id == dept_id:
                return dept
        return None
