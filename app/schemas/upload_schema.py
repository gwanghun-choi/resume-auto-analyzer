from pydantic import BaseModel, Field
from typing import List

# 업로드 결과를 화면에 돌려줄 때 쓰는 Schema(DTO) 입니다.
#
# 흐름: 파일 업로드 -> 서버가 로컬에 저장 -> upload_id 와 저장된 파일 목록을 응답.
# 이후 분석 단계에서 이 upload_id 로 "어떤 파일들을 분석할지" 찾습니다.

class UploadResponse(BaseModel):
    upload_id: str = Field(..., description="이번 업로드 묶음 ID (분석 시 사용)")
    dept_id: str = Field(..., description="업로드 대상 팀 ID")
    files: List[str] = Field(default_factory=list, description="실제로 저장된 파일명 목록")
