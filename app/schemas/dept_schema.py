from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

# Pydantic Schema 는 Java/Spring 의 DTO 와 같은 역할을 합니다.
# 아래 Dept 는 자바의 DeptVO(extends BaseVO) 를 파이썬으로 옮긴 것입니다.
#
# Java 원본:
#   public class DeptVO extends BaseVO {
#       String id; String name; String parentId; String managerId;
#       String email; int sort; int status; Date registerDate; Date updateDate;
#   }
#
# 파이썬에서는 camelCase 대신 snake_case 를 씁니다. (parentId -> parent_id)
# Optional[X] 는 자바로 치면 "null 이 들어올 수 있는 필드" 라는 뜻입니다.

class Dept(BaseModel):
    id: str = Field(..., description="부서 ID")
    name: str = Field(..., description="부서명")
    parent_id: Optional[str] = Field(None, description="상위 부서 ID (없으면 최상위)")
    manager_id: Optional[str] = Field(None, description="부서장(매니저) ID")
    email: Optional[str] = Field(None, description="부서 대표 이메일")
    sort: int = Field(0, description="정렬 순서")
    status: int = Field(1, description="상태값 (1=사용, 0=미사용)")
    register_date: Optional[datetime] = Field(None, description="등록일")
    update_date: Optional[datetime] = Field(None, description="수정일")
