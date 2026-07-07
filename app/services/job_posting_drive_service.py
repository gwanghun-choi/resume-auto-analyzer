from app.services.google_drive_service import GoogleDriveService, _log
from app.services.dept_folder_sync_service import sanitize_folder_name

# 공고별 Google Drive 폴더를 생성/조회합니다.
# 구조(2026-06 정책): 부서 폴더를 두지 않고 공고명 기준으로 바로 생성합니다.
#   resume-demo-root / inbox     / {JP000001_공고명}
#   resume-demo-root / completed / {JP000001_공고명}
#   resume-demo-root / failed    / {JP000001_공고명}
#
# 정책:
# - 기존 root 의 inbox/completed/failed(ensure_project_folders) 아래에 공고 폴더를 생성합니다.
# - 같은 부모 아래 동일 이름 폴더가 있으면 재사용(get_or_create_folder).
# - 폴더명 특수문자는 sanitize_folder_name 으로 _ 치환, 너무 길면 잘라냅니다.
# - 기존 postings/{부서}/... 구조는 더 이상 생성하지 않습니다(기존 폴더는 삭제하지 않음 — legacy).

SUB_FOLDERS = ["inbox", "completed", "failed"]
MAX_FOLDER_NAME = 100   # 공고 폴더명 최대 길이(관리 편의)


def posting_code(posting_id: int) -> str:
    """공고 폴더 접두 코드. 예: 1 -> JP000001"""
    return f"JP{int(posting_id):06d}"


def posting_folder_name(posting_id: int, title: str) -> str:
    """공고 폴더명: JP{id}_{공고명}. 특수문자 _ 치환 + 길이 제한."""
    name = sanitize_folder_name(f"{posting_code(posting_id)}_{title or ''}".rstrip("_ "))
    return name[:MAX_FOLDER_NAME].rstrip("_ ") or posting_code(posting_id)


def ensure_posting_folders(drive: GoogleDriveService, posting_id: int, title: str) -> dict:
    """
    root 의 inbox/completed/failed 아래에 공고 폴더를 생성/조회하고 folder id 들을 반환합니다.
    반환: {"drive_folder_id"(=None), "inbox", "completed", "failed", "folder_name"}
    실패 시 예외를 그대로 던집니다(호출부에서 트랜잭션 롤백 처리).
    """
    base = drive.ensure_project_folders()    # root + config/inbox/completed/failed 보장(기존 로직)
    parents = base["folders"]                # {config, inbox, completed, failed}
    folder_name = posting_folder_name(posting_id, title)

    ids = {}
    for sub in SUB_FOLDERS:
        ids[sub] = drive.get_or_create_folder(folder_name, parents[sub])
    _log(f"[posting-drive] 공고 폴더 생성/조회: inbox|completed|failed/{folder_name}")

    return {
        "drive_folder_id": None,   # 단일 상위 폴더 없음(공고명 폴더가 inbox/completed/failed 각각에 존재)
        "inbox": ids["inbox"],
        "completed": ids["completed"],
        "failed": ids["failed"],
        "folder_name": folder_name,
    }
