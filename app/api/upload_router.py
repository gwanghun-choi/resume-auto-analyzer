from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from typing import List

from app.schemas.upload_schema import UploadResponse
from app.services.upload_service import UploadService

# ============================= LEGACY =============================
# LEGACY ROUTER — 부서(팀) 기준 로컬 파일시스템 업로드 API (/api/uploads).
# 공고 중심 전환으로 신규 개발 대상이 아닙니다. 신규 이력서 업로드는
# POST /api/resumes/upload-to-drive (공고 기준 Drive 업로드, resume_drive_upload_service)를 사용하세요.
# 프론트 런타임 호출 없음(app.js 헤더 주석에만 존재). 하위호환 위해 유지 — 동작 변경 금지, 후속 제거 검토(docs/TODO).
# =================================================================

router = APIRouter(prefix="/api/uploads", tags=["Upload"])


def get_upload_service():
    return UploadService()


@router.post("/{dept_id}", response_model=UploadResponse)
async def upload_files(
    dept_id: str,
    files: List[UploadFile] = File(..., description="이력서 파일 (PDF, DOCX, ZIP)"),
    service: UploadService = Depends(get_upload_service),
):
    """
    선택한 팀에 이력서 파일을 업로드합니다.
    - PDF, DOCX, ZIP 허용
    - ZIP 이면 내부의 PDF/DOCX 만 추출하여 저장
    - 저장 경로: data/storage/uploads/{dept_id}/YYYY/MM/DD/{upload_id}/
    - 응답: upload_id 와 저장된 파일 목록
    """
    # UploadFile -> (파일명, 바이트) 형태로 읽어서 서비스에 넘깁니다.
    payload = [(f.filename, await f.read()) for f in files]
    upload_id, saved = service.save_uploads(dept_id, payload)

    if not saved:
        # 저장된 문서가 하나도 없으면(허용 확장자 아님 등) 안내합니다.
        raise HTTPException(
            status_code=400,
            detail="저장된 파일이 없습니다. PDF/DOCX 또는 PDF/DOCX 가 들어있는 ZIP 을 업로드해주세요.",
        )

    return UploadResponse(upload_id=upload_id, dept_id=dept_id, files=saved)
