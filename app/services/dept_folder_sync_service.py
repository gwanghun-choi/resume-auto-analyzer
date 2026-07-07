import json
import re
from datetime import datetime

from app.services.google_drive_service import GoogleDriveService, PROJECT_ROOT, _log
from app.services import dept_drive_folder_db_service

# DeptFolderSyncService 는 Drive 의 config/dept_config.json(departments 배열)을 기준으로
# Google Drive 의 inbox/completed/failed 아래에 부서 폴더(평탄화 구조)를 동기화합니다.
#
# 정책:
# - 트리 구조(parent_id)는 사용하지 않습니다. (화면 트리 표시용일 뿐) → Drive 는 평탄화
# - status == 1 인 부서만 대상으로 합니다.
# - 폴더명은 "{dept_id}_{dept_name}" 형식이며 특수문자는 _ 로 치환합니다.
# - 같은 부모 아래 동일 이름 폴더가 있으면 새로 만들지 않고 기존 folder_id 를 재사용합니다.
# - 삭제/이름변경(rename)은 하지 않습니다. (추후 과제)

# 동기화 결과를 저장할 로컬 매핑 파일 (프로젝트 루트 기준 고정)
MAP_FILE_REL = "data/google_drive/dept_folder_map.json"
MAP_DIR = PROJECT_ROOT / "data" / "google_drive"
MAP_PATH = MAP_DIR / "dept_folder_map.json"

# inbox/completed/failed — 각 부모 아래에 동일한 부서 폴더를 만듭니다.
PARENT_KEYS = ["inbox", "completed", "failed"]

# Google Drive 에서 문제가 될 수 있는 특수문자 (Windows 파일명 금지문자 기준)
_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')


def sanitize_folder_name(name: str) -> str:
    """폴더명에서 Drive/파일시스템에 문제될 특수문자를 _ 로 치환합니다."""
    return _INVALID_CHARS.sub("_", name).strip()


def read_sync_status() -> dict:
    """
    동기화 상태(매핑 파일) 를 읽어 요약합니다. (Drive 인증 불필요)
    last_synced_at 은 항목들의 synced_at 중 가장 최근 값을 사용합니다.
    """
    if not MAP_PATH.exists():
        return {
            "exists": False,
            "map_file": MAP_FILE_REL,
            "folder_count": 0,
            "last_synced_at": None,
        }

    data = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    synced_times = [e.get("synced_at") for e in data.values() if e.get("synced_at")]
    return {
        "exists": True,
        "map_file": MAP_FILE_REL,
        "folder_count": len(data),
        "last_synced_at": max(synced_times) if synced_times else None,
    }


class DeptFolderSyncService:
    def __init__(self, drive: GoogleDriveService):
        # 이미 인증/ build 까지 끝난 GoogleDriveService 를 주입받습니다.
        self._drive = drive

    def sync(self, departments: list) -> dict:
        """
        주어진 departments(DB resume_ai.departments 기준) 로 inbox/completed/failed 아래에
        부서 폴더를 평탄화 생성/조회하고, 결과를 **resume_ai.dept_drive_folders** 에 upsert 합니다.
        (map.json 은 debug 용으로 함께 남깁니다.)
        반환: {status, source, target, total_depts, active_depts, created, reused, updated, failed, ...}
        """
        # 1) inbox/completed/failed 부모 폴더 id 확보 (없으면 생성)
        base = self._drive.ensure_project_folders()
        parents = base["folders"]

        # 2) status == 1 인 부서만 폴더 생성 대상으로 합니다.
        active = [d for d in departments if isinstance(d, dict) and d.get("status", 1) == 1]
        _log(f"[sync] 전체 부서: {len(departments)}, status=1 대상: {len(active)}")

        new_map: dict = {}
        created = reused = updated = failed = 0

        for d in active:
            dept_id = d.get("id")
            dept_name = d.get("name", "")
            try:
                if not dept_id:
                    failed += 1
                    continue

                folder_name = sanitize_folder_name(f"{dept_id}_{dept_name}")
                # 14) 기존 dept_id 매핑(DB)이 있으면 folder_id 를 그대로 재사용합니다. (rename/삭제 안 함)
                existing = dept_drive_folder_db_service.get_folder(dept_id)
                folder_ids = {}
                if existing and existing.get("inbox_folder_id") \
                        and existing.get("completed_folder_id") and existing.get("failed_folder_id"):
                    for key in PARENT_KEYS:
                        folder_ids[key] = existing[f"{key}_folder_id"]
                    folder_name = existing.get("folder_name") or folder_name
                    reused += 1
                else:
                    # inbox/completed/failed 각각에 동일한 부서 폴더 생성/조회 (이름 중복 방지)
                    for key in PARENT_KEYS:
                        folder_ids[key] = self._drive.get_or_create_folder(folder_name, parents[key])
                    created += 1
                    _log(f"[sync] 생성: {folder_name}")

                # 6) DB(resume_ai.dept_drive_folders) 에 upsert
                dept_drive_folder_db_service.upsert_folder(
                    dept_id, dept_name, folder_name,
                    folder_ids["inbox"], folder_ids["completed"], folder_ids["failed"],
                )
                updated += 1

                # debug 용 map.json entry
                new_map[dept_id] = {
                    "dept_name": dept_name, "folder_name": folder_name,
                    "synced_at": datetime.now().isoformat(timespec="seconds"),
                    "inbox_folder_id": folder_ids["inbox"],
                    "completed_folder_id": folder_ids["completed"],
                    "failed_folder_id": folder_ids["failed"],
                }
            except Exception as e:
                failed += 1
                _log(f"[sync] 실패: {dept_id}_{dept_name}: {type(e).__name__}: {e}")

        # 동기화 결과를 로컬 매핑 파일로도 저장합니다. (debug/fallback)
        self._save_map(new_map)
        _log(f"[sync] 완료 — total={len(departments)} active={len(active)} "
             f"created={created} reused={reused} updated={updated} failed={failed}")

        return {
            "status": "OK",
            "source": "db_departments",
            "target": "resume_ai.dept_drive_folders",
            "total_depts": len(departments),
            "active_depts": len(active),
            "created": created,
            "reused": reused,
            "updated": updated,
            "skipped": 0,
            "failed": failed,
            "map_file": MAP_FILE_REL,
            "synced_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _save_map(self, data: dict) -> None:
        """매핑 파일을 프로젝트 루트의 고정 경로에 저장합니다."""
        MAP_DIR.mkdir(parents=True, exist_ok=True)
        MAP_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
