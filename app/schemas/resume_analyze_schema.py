from typing import List, Optional
from pydantic import BaseModel

# 분석 실행 요청 바디입니다.
# upload_id 가 있으면 해당 업로드 회차만, 없으면 부서의 모든 분석 대기 파일을 분석합니다.


class AnalyzePendingRequest(BaseModel):
    dept_id: str = ""
    upload_id: Optional[str] = None


class AnalyzeSelectedRequest(BaseModel):
    """선택 항목 분석: 체크된 resume_file_id 목록만 분석합니다. (권한/PENDING 여부는 백엔드에서 재검증)"""
    resume_file_ids: List[int] = []


class AnalyzePostingRequest(BaseModel):
    """선택 공고 분석: 해당 공고의 분석 대기 파일을 공고 active JD 기준으로 분석합니다."""
    posting_id: int


# '전체 분석'(scope=all) 은 별도 요청 바디가 없습니다. 백엔드가 현재 사용자 권한 범위로 대상을 계산합니다.
