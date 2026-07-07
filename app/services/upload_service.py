import io
import os
import uuid
import zipfile
from pathlib import Path
from datetime import datetime
from typing import List, Tuple

# LEGACY: 부서 기준 + 로컬 파일시스템(data/storage) 업로드 서비스. 공고 중심 전환으로 신규 개발 대상이 아닙니다.
#         신규 업로드는 공고 기준 Drive 업로드(resume_drive_upload_service)를 사용하세요.
#         (upload_router 에서만 사용. 동작 변경 금지, 후속 제거 검토 — docs/TODO.)
#
# UploadService 는 "선택한 팀(dept_id)에 이력서 파일을 저장" 하는 서비스입니다.
#
# 지금은 로컬 파일 시스템에 저장하지만, 나중에 Object Storage(S3 등)나 NAS 로
# 교체할 수 있도록 저장 로직을 이 클래스 한 곳에 모아 두었습니다.
# (라우터에는 저장 코드를 길게 쓰지 않습니다.)
#
# 저장 경로 규칙:
#   data/storage/uploads/{dept_id}/YYYY/MM/DD/{upload_id}/{파일들}
#
# ZIP 정책:
#   - ZIP 안에서는 .pdf, .docx 만 꺼냅니다.
#   - ZIP 내부 경로 공격(../ 같은 경로 탈출)을 막습니다. (파일명만 사용)

UPLOADS_DIR = Path("data/storage/uploads")

# 업로드 가능한 확장자 (개별 파일)
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".zip"}
# 실제 분석 대상이 되는 문서 확장자 (ZIP 내부 포함)
DOCUMENT_EXTENSIONS = {".pdf", ".docx"}


class UploadService:
    def _base_dir(self, dept_id: str, upload_id: str) -> Path:
        """오늘 날짜 + 팀ID + upload_id 기준 저장 폴더 경로를 만듭니다."""
        now = datetime.now()
        return UPLOADS_DIR / dept_id / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d") / upload_id

    def save_uploads(self, dept_id: str, files: List[Tuple[str, bytes]]) -> Tuple[str, List[str]]:
        """
        업로드된 파일들을 저장합니다.
        files: [(파일명, 내용 bytes), ...]
        반환: (upload_id, 저장된 문서 파일명 리스트)

        - .zip 은 풀어서 내부의 pdf/docx 만 저장합니다.
        - .pdf/.docx 는 그대로 저장합니다.
        - 파일명이 겹치면 안전하게 이름을 바꿉니다. (name_1.pdf 식)
        """
        upload_id = uuid.uuid4().hex[:12]
        base_dir = self._base_dir(dept_id, upload_id)
        base_dir.mkdir(parents=True, exist_ok=True)

        saved_names: List[str] = []

        for filename, content in files:
            ext = Path(filename).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                # 허용하지 않는 확장자는 조용히 건너뜁니다. (전체 실패로 만들지 않음)
                continue

            if ext == ".zip":
                saved_names.extend(self._extract_zip(content, base_dir, saved_names))
            else:
                safe_name = self._dedup_name(Path(filename).name, saved_names)
                (base_dir / safe_name).write_bytes(content)
                saved_names.append(safe_name)

        return upload_id, saved_names

    def _extract_zip(self, content: bytes, base_dir: Path, existing: List[str]) -> List[str]:
        """ZIP 내부에서 pdf/docx 만 꺼내 저장하고, 저장된 파일명 리스트를 반환합니다."""
        added: List[str] = []
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                # 경로 탈출 방지를 위해 디렉터리 경로는 버리고 '파일명' 만 사용합니다.
                inner_name = os.path.basename(info.filename)
                if not inner_name:
                    continue
                ext = Path(inner_name).suffix.lower()
                if ext not in DOCUMENT_EXTENSIONS:
                    # ZIP 안의 pdf/docx 가 아닌 파일은 무시합니다.
                    continue

                safe_name = self._dedup_name(inner_name, existing + added)
                (base_dir / safe_name).write_bytes(zf.read(info))
                added.append(safe_name)
        return added

    def _dedup_name(self, filename: str, used: List[str]) -> str:
        """이미 쓰인 파일명이면 name_1.ext, name_2.ext ... 로 안전하게 바꿉니다."""
        if filename not in used:
            return filename
        stem = Path(filename).stem
        ext = Path(filename).suffix
        counter = 1
        while f"{stem}_{counter}{ext}" in used:
            counter += 1
        return f"{stem}_{counter}{ext}"

    def list_files(self, dept_id: str, upload_id: str) -> List[Path]:
        """
        upload_id 에 해당하는 저장된 문서 파일들의 실제 경로를 찾습니다.
        저장 경로에 날짜가 포함되므로 glob 으로 upload_id 폴더를 찾습니다.
        """
        dept_root = UPLOADS_DIR / dept_id
        if not dept_root.exists():
            return []
        # data/storage/uploads/{dept_id}/YYYY/MM/DD/{upload_id}/
        matches = list(dept_root.glob(f"*/*/*/{upload_id}"))
        if not matches:
            return []
        target_dir = matches[0]
        return sorted(
            p for p in target_dir.iterdir()
            if p.is_file() and p.suffix.lower() in DOCUMENT_EXTENSIONS
        )
