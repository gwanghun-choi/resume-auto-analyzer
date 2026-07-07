from typing import List
from pydantic import BaseModel

# 부서 설정 JSON 저장/검증 요청 바디입니다.
# departments 항목은 부서마다 키 구성이 다를 수 있어(dict) 자유 형태로 받습니다.
# (실제 구조 검증은 dept_config_service.validate_departments 에서 수행합니다.)


class DeptConfigRequest(BaseModel):
    departments: List[dict]
