import json
import os
from pathlib import Path
from typing import Any, List

from app.schemas.dept_schema import Dept

# 이 파일은 "부서 JSON 파일" 을 읽어서 Dept 리스트로 변환해 주는 로더(loader) 입니다.
#
# 예전에는 app/data/dummy_depts.py 에 부서 목록을 코드로 하드코딩했지만,
# 이제는 샘플 파일(data/dummy/departments.sample.json)을 읽습니다.
# 실제 조직도를 쓰려면 같은 스키마의 파일을 DEPT_JSON_PATH 경로에 두거나 DEPT_JSON_PATH 를 바꾸세요.
# (실제 조직도 데이터는 Git 에 커밋하지 마세요.)
#
# Java/Spring 비유: 메모리에 박아둔 List<DeptVO> 대신,
#                  파일을 읽어 DTO 리스트로 매핑하는 간단한 Repository 라고 보면 됩니다.

# 부서 JSON 경로. 저장소에는 가상 조직도 샘플만 포함합니다.
DEPT_JSON_PATH = Path(os.getenv("DEPT_JSON_PATH", "data/dummy/departments.sample.json"))


def load_depts() -> List[Dept]:
    """
    부서 JSON 을 읽어 부서 리스트를 반환합니다.

    - 같은 parent_id 를 가진 부서들끼리 sort 오름차순, 그다음 name 오름차순으로 정렬합니다.
    - parent_id 가 빈 문자열("")이면 None 으로 바꿉니다. (루트 판단을 위해)
    """
    raw = json.loads(DEPT_JSON_PATH.read_text(encoding="utf-8"))
    rows = _extract_rows(raw)
    depts = [_to_dept(row) for row in rows]

    # 같은 parent_id 묶음 안에서 sort -> name 오름차순.
    # (parent_id 별로 그룹화하지 않아도, 정렬 키 맨 앞에 parent_id 를 두면 형제끼리 순서가 맞습니다.)
    depts.sort(key=lambda d: ((d.parent_id or ""), d.sort, d.name))
    return depts


def _extract_rows(raw: Any) -> List[dict]:
    """
    JSON 최상위에서 '부서 배열' 을 꺼냅니다.

    - JSON 자체가 배열이면 그대로 사용합니다.
    - JSON 이 객체(dict)면 '첫 번째 value' 를 부서 배열로 사용합니다.
      (DB 클라이언트로 export 한 파일은 최상위에 SQL 문자열 key 가 있는데, 그 key 이름을 코드에 하드코딩하지 않습니다.)
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return next(iter(raw.values()))
    raise ValueError("부서 JSON 형식을 인식할 수 없습니다. (배열 또는 객체가 아님)")


def _to_dept(row: dict) -> Dept:
    """JSON 한 줄(dict)을 Dept 로 변환합니다. 빈 문자열 값은 안전하게 정리합니다."""
    return Dept(
        id=row["id"],
        name=row["name"],
        # 빈 문자열 parent_id 는 None 으로. ("" -> None)  루트 노드 판단을 위함.
        parent_id=(row.get("parent_id") or None),
        # manager_id / email 은 빈 문자열이어도 그대로 둡니다. (화면 표시에 문제 없음)
        manager_id=row.get("manager_id"),
        email=row.get("email"),
        sort=row.get("sort", 0),
        status=row.get("status", 1),
        # 날짜가 비어있을 수 있어 빈 값이면 None 으로. (Pydantic 이 ISO 문자열을 datetime 으로 파싱)
        register_date=(row.get("register_date") or None),
        update_date=(row.get("update_date") or None),
    )
