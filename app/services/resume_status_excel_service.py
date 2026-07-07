from io import BytesIO

from openpyxl import Workbook

# 이력서 현황 목록을 Excel(.xlsx)로 생성합니다. (openpyxl, BytesIO -> StreamingResponse 용)
# 임시 파일을 남기지 않고 메모리에서 생성합니다.

# Excel 헤더(표시 컬럼). get_status_export_rows 의 dict key 와 순서를 맞춥니다.
EXCEL_HEADERS = [
    ("posting_title", "공고명"),
    ("dept_id", "부서 ID"),
    ("dept_name", "부서명"),
    ("upload_id", "업로드 ID"),
    ("upload_folder_name", "업로드 폴더명"),
    ("upload_type", "업로드 유형"),
    ("original_file_name", "원본 파일명"),
    ("stored_file_name", "저장 파일명"),
    ("file_status", "파일 상태"),
    ("analysis_status", "분석 상태"),
    ("score", "점수"),
    ("recommendation", "추천"),
    ("summary", "요약"),
    ("strengths", "강점"),
    ("weaknesses", "보완점"),
    ("matched_skills", "매칭 기술"),
    ("missing_skills", "부족 기술"),
    ("moved_to", "이동 위치"),
    ("move_status", "이동 상태"),
    ("error_code", "에러 코드"),
    ("error_message", "에러 메시지"),
    ("uploaded_at", "업로드 일시"),
    ("analyzed_at", "분석 일시"),
]

# JSONB 리스트(강점/보완점/매칭/부족 기술)는 줄바꿈으로 보기 좋게 변환합니다.
_LIST_KEYS = {"strengths", "weaknesses", "matched_skills", "missing_skills"}


def _cell_value(key, value):
    if value is None:
        return ""
    if key in _LIST_KEYS and isinstance(value, (list, tuple)):
        return "\n".join(str(x) for x in value)
    return value


def build_status_excel(rows: list) -> BytesIO:
    """행(dict) 목록으로 .xlsx 를 메모리에 생성해 BytesIO 로 반환합니다. (데이터가 없어도 헤더만 출력)"""
    wb = Workbook()
    ws = wb.active
    ws.title = "이력서 현황"
    ws.append([label for _, label in EXCEL_HEADERS])
    for r in rows:
        ws.append([_cell_value(key, r.get(key)) for key, _ in EXCEL_HEADERS])
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio
