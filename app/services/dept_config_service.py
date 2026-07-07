import json
from datetime import datetime

from app.data.dummy_dept_loader import DEPT_JSON_PATH
from app.services.google_drive_service import GoogleDriveService, PROJECT_ROOT, _log

# DeptConfigService 는 Google Drive 의 config/dept_config.json 을
# "부서 데이터 원천" 으로 관리합니다. (조회 / 업로드 정규화 / 검증 / 저장)
#
# 화면(JD 등록 / 이력서 등록)의 부서 트리는 매번 Drive 를 호출하지 않고
# 로컬 캐시(data/google_drive/dept_config_cache.json)를 기준으로 표시합니다.
#
# 중요: 정규화는 LLM 없이 **규칙 기반** 으로만 처리합니다.
#       부서 id/name/status 를 AI 로 추론하거나 원본 데이터를 임의로 바꾸지 않습니다.
#       (status 없으면 1, sort 없으면 0 정도의 기본값 보정만 허용)

CONFIG_FILE_NAME = "dept_config.json"

# 화면 트리 표시용 로컬 캐시 (Drive 를 매번 호출하지 않기 위함)
CACHE_FILE_REL = "data/google_drive/dept_config_cache.json"
CACHE_DIR = PROJECT_ROOT / "data" / "google_drive"
CACHE_PATH = CACHE_DIR / "dept_config_cache.json"


class DeptConfigError(Exception):
    """
    부서 설정 JSON 처리(정규화/검증/저장) 중 발생하는 '사용자 입력' 오류입니다.
    라우터에서 잡아 {status, step, error_message, hint} JSON 으로 돌려줍니다.
    """
    def __init__(self, message: str, step: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.step = step
        self.hint = hint


def _apply_defaults(dept: dict) -> dict:
    """status 없으면 1, sort 없으면 0 만 보정합니다. (그 외 값/키는 변경하지 않음)"""
    out = dict(dept)
    out.setdefault("status", 1)
    out.setdefault("sort", 0)
    return out


def _active_count(departments) -> int:
    return sum(1 for d in departments if isinstance(d, dict) and d.get("status", 1) == 1)


def normalize_raw(raw, step: str = "normalize") -> dict:
    """
    파싱된 JSON(raw) 을 departments 배열로 정규화합니다. (규칙 기반)
    반환: {departments, detected_format, normalize_rule, warnings}

    - root 가 배열이면 그대로 사용 (detected_format=array, rule=root_array)
    - root 가 객체면 value 중 첫 번째 배열을 사용 (rule=first_array_value)
      * key 가 SQL 문자열(select ...)이면 dbeaver_export, 아니면 object_first_array
      * 배열 value 가 여러 개면 첫 번째를 쓰되 warning 추가
    - 배열을 찾을 수 없으면 에러
    """
    warnings = []

    if isinstance(raw, list):
        departments = raw
        detected_format = "array"
        normalize_rule = "root_array"
    elif isinstance(raw, dict):
        array_items = [(k, v) for k, v in raw.items() if isinstance(v, list)]
        if not array_items:
            raise DeptConfigError(
                "업로드된 JSON에서 부서 배열을 찾을 수 없습니다.",
                step=step,
                hint="배열 JSON 또는 DBeaver export JSON 형태인지 확인하세요.",
            )
        first_key, departments = array_items[0]
        normalize_rule = "first_array_value"
        key_lower = first_key.strip().lower()
        if key_lower.startswith("select") or " from " in key_lower:
            detected_format = "dbeaver_export"
        else:
            detected_format = "object_first_array"
        if len(array_items) > 1:
            warnings.append(
                f"배열 value 가 여러 개라 첫 번째('{first_key}') 배열을 사용했습니다."
            )
    else:
        raise DeptConfigError(
            "JSON 최상위가 배열도 객체도 아닙니다.",
            step=step,
            hint="배열 JSON 또는 DBeaver export JSON 형태인지 확인하세요.",
        )

    departments = [_apply_defaults(d) if isinstance(d, dict) else d for d in departments]
    return {
        "departments": departments,
        "detected_format": detected_format,
        "normalize_rule": normalize_rule,
        "warnings": warnings,
    }


def validate_departments(departments, step: str = "validate_dept_config") -> dict:
    """
    departments 구조를 검증합니다. 실패 시 DeptConfigError, 성공 시 카운트 반환.
    - 배열이어야 함 / 각 항목은 객체 / id·name 필수 / id 중복 금지
    """
    if not isinstance(departments, list):
        raise DeptConfigError(
            "departments는 배열이어야 합니다.", step=step,
            hint="departments는 배열 형태여야 합니다.",
        )
    seen = set()
    for d in departments:
        if not isinstance(d, dict):
            raise DeptConfigError(
                "부서 항목은 객체(JSON object)여야 합니다.", step=step,
                hint="각 부서는 id와 name을 가진 객체여야 합니다.",
            )
        if not d.get("id"):
            raise DeptConfigError(
                "id가 없는 부서가 있습니다.", step=step,
                hint="모든 부서는 id와 name을 가져야 합니다.",
            )
        if not d.get("name"):
            raise DeptConfigError(
                "name이 없는 부서가 있습니다.", step=step,
                hint="모든 부서는 id와 name을 가져야 합니다.",
            )
        if d["id"] in seen:
            raise DeptConfigError(
                f"중복된 부서 id가 있습니다: {d['id']}", step=step,
                hint="부서 id는 고유해야 합니다.",
            )
        seen.add(d["id"])

    return {
        "dept_count": len(departments),
        "active_dept_count": _active_count(departments),
        "warnings": [],
    }


def normalize_upload(file_bytes: bytes, original_file_name: str) -> dict:
    """
    업로드된 JSON 파일을 규칙 기반으로 정규화합니다. (Drive 저장 안 함, 순수 함수)
    화면에서 확인/수정할 수 있도록 정규화 결과만 반환합니다.
    """
    try:
        raw = json.loads(file_bytes)
    except (ValueError, UnicodeDecodeError) as e:
        raise DeptConfigError(
            f"업로드된 파일을 JSON 으로 파싱하지 못했습니다: {e}",
            step="normalize_upload",
            hint="유효한 JSON 파일인지 확인하세요.",
        )

    norm = normalize_raw(raw, step="normalize_upload")
    departments = norm["departments"]
    return {
        "status": "OK",
        "source": "uploaded_file",
        "original_file_name": original_file_name,
        "detected_format": norm["detected_format"],
        "normalize_rule": norm["normalize_rule"],
        "warnings": norm["warnings"],
        "dept_count": len(departments),
        "active_dept_count": _active_count(departments),
        "departments": departments,
    }


# ----- 화면 트리용 로컬 캐시 / 트리 구성 (Drive 인증 불필요) -----

def load_departments_from_cache() -> dict:
    """캐시 파일을 읽습니다. 없거나 깨졌으면 None 을 반환합니다."""
    if not CACHE_PATH.exists():
        return None
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None


def save_cache(departments, source: str, dept_config_file_id: str = None) -> dict:
    """
    정규화된 departments(배열)와 메타데이터를 로컬 캐시로 저장합니다.
    캐시에는 항상 '배열 형태' departments 를 저장합니다. (DBeaver export 형태 금지)
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = {
        "source": source,
        "dept_config_file_id": dept_config_file_id,
        "cached_at": datetime.now().isoformat(timespec="seconds"),
        "dept_count": len(departments),
        "active_dept_count": _active_count(departments),
        "departments": departments,
    }
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return cache


def read_cache_status() -> dict:
    """캐시 상태를 요약합니다. (존재 여부 / 카운트 / 갱신 시각)"""
    cache = load_departments_from_cache()
    if not cache:
        return {"exists": False, "cache_file": CACHE_FILE_REL,
                "dept_count": 0, "active_dept_count": 0, "cached_at": None}
    return {
        "exists": True,
        "cache_file": CACHE_FILE_REL,
        "dept_count": cache.get("dept_count", len(cache.get("departments", []))),
        "active_dept_count": cache.get("active_dept_count", 0),
        "cached_at": cache.get("cached_at"),
    }


def _dept_parent_id(dept: dict):
    """부서의 상위 id 를 꺼냅니다. (parentId/parent_id 모두 지원, 빈 문자열은 루트)"""
    parent = dept.get("parentId")
    if parent is None:
        parent = dept.get("parent_id")
    return parent or None


def build_department_tree(departments) -> list:
    """
    departments(배열)를 parentId 기준 중첩 트리로 구성합니다.
    - 같은 부모 아래 형제는 sort 오름차순 → name 오름차순 (기존 화면 정책 유지)
    - 내부 식별은 항상 dept_id 기준 (이름 중복 가능)
    - 기존 화면과 동일하게 전체 부서를 표시합니다. (status 별도 필터 안 함)
    반환: [{id, name, children:[...]}, ...]
    """
    children_of = {}
    for d in departments:
        if not isinstance(d, dict):
            continue
        key = _dept_parent_id(d) or "ROOT"
        children_of.setdefault(key, []).append(d)
    for siblings in children_of.values():
        siblings.sort(key=lambda x: (x.get("sort", 0), str(x.get("name", ""))))

    def build(parent_key):
        nodes = []
        for d in children_of.get(parent_key, []):
            nodes.append({
                "id": d.get("id"),
                "name": d.get("name"),
                "children": build(d.get("id")),
            })
        return nodes

    return build("ROOT")


class DeptConfigService:
    def __init__(self, drive: GoogleDriveService):
        # 이미 인증/build 까지 끝난 GoogleDriveService 를 주입받습니다.
        self._drive = drive

    def _config_folder_id(self) -> str:
        """resume-demo-root/config 폴더 id (없으면 생성됨)."""
        return self._drive.ensure_project_folders()["folders"]["config"]

    def _get_or_seed(self) -> dict:
        """
        config/dept_config.json 을 찾고, 없으면 로컬 더미로 최초 1회 생성합니다.
        (이미 있으면 덮어쓰지 않고 그대로 사용)
        반환: {file(메타), created_from_local_dummy, config_folder_id}
        """
        config_id = self._config_folder_id()
        existing = self._drive.find_file(CONFIG_FILE_NAME, config_id)
        if existing:
            return {
                "file": existing,
                "created_from_local_dummy": False,
                "config_folder_id": config_id,
            }

        # 최초 seed: 로컬 더미 JSON 을 정규화해서 '배열 형태' 로 Drive 에 저장합니다.
        _log(f"[dept-config] dept_config.json 없음 → 로컬 더미로 최초 생성: {DEPT_JSON_PATH}")
        raw = json.loads(DEPT_JSON_PATH.read_text(encoding="utf-8"))
        norm = normalize_raw(raw, step="seed_dept_config")
        content = json.dumps(norm["departments"], ensure_ascii=False, indent=2)
        file_id = self._drive.create_text_file(CONFIG_FILE_NAME, config_id, content)
        return {
            "file": self._drive.get_file_metadata(file_id),
            "created_from_local_dummy": True,
            "config_folder_id": config_id,
        }

    def read(self) -> dict:
        """
        config/dept_config.json 을 조회합니다. (없으면 로컬 더미로 최초 생성)
        다운로드 후 departments 배열로 정규화해서 반환합니다.

        실패 단계를 step 으로 구분합니다:
          - 폴더/파일 조회 실패: drive_config_folder_lookup_failed
          - 다운로드 실패: dept_config_download_failed
          - JSON 파싱 실패: dept_config_json_parse_failed
        """
        # 1) config 폴더/파일 조회 (없으면 로컬 더미로 seed)
        _log("[drive-config] file list start")
        try:
            seed = self._get_or_seed()
        except DeptConfigError:
            raise
        except Exception as e:
            # 실제 예외 타입/메시지를 남깁니다. (예: SSL CERTIFICATE_VERIFY_FAILED 식별용)
            _log("[drive-config] file list failed")
            _log(f"[drive-config] list error type = {type(e).__name__}")
            _log(f"[drive-config] list error message = {e}")
            raise DeptConfigError(
                "Google Drive의 config 폴더/파일 조회 중 오류가 발생했습니다.",
                "drive_config_folder_lookup_failed",
                "resume-demo-root/config 폴더와 Drive 접근 권한을 확인해주세요.",
            ) from e
        file = seed["file"]
        file_id = file["id"]
        _log(f"[drive-config] dept_config file id = {file_id}")

        # 2) 파일 다운로드
        try:
            text = self._drive.download_text(file_id)
            _log("[drive-config] download success")
        except Exception as e:
            raise DeptConfigError(
                "Google Drive dept_config.json 다운로드 중 오류가 발생했습니다.",
                "dept_config_download_failed",
                "Drive 파일 권한과 Google Drive API 접근 권한을 확인해주세요.",
            ) from e

        # 3) JSON 파싱
        try:
            raw = json.loads(text)
        except Exception as e:
            raise DeptConfigError(
                "dept_config.json 파싱 중 오류가 발생했습니다.",
                "dept_config_json_parse_failed",
                "JSON 형식이 올바른지 확인해주세요.",
            ) from e

        norm = normalize_raw(raw, step="read_dept_config")
        departments = norm["departments"]
        return {
            "status": "OK",
            "source": "google_drive",
            "file_name": CONFIG_FILE_NAME,
            "file_id": file_id,
            "config_folder_id": seed["config_folder_id"],
            "created_from_local_dummy": seed["created_from_local_dummy"],
            "detected_format": norm["detected_format"],
            "normalize_rule": norm["normalize_rule"],
            "warnings": norm["warnings"],
            "dept_count": len(departments),
            "active_dept_count": _active_count(departments),
            "modified_time": file.get("modifiedTime"),
            "departments": departments,
        }

    def save(self, departments) -> dict:
        """
        departments 를 검증한 뒤 config/dept_config.json 을 '배열 JSON' 으로 저장합니다.
        (DBeaver export 형태로 저장하지 않습니다.) 검증 실패 시 Drive 를 건드리지 않습니다.
        저장 후 다시 읽어 결과를 반환합니다.
        """
        validate_departments(departments)  # 실패 시 DeptConfigError → Drive 미변경
        departments = [_apply_defaults(d) for d in departments]

        config_id = self._config_folder_id()
        existing = self._drive.find_file(CONFIG_FILE_NAME, config_id)
        content = json.dumps(departments, ensure_ascii=False, indent=2)
        if existing:
            self._drive.update_text_file(existing["id"], content)
            file_id = existing["id"]
        else:
            file_id = self._drive.create_text_file(CONFIG_FILE_NAME, config_id, content)

        # 저장 후 재조회
        meta = self._drive.get_file_metadata(file_id)
        stored = json.loads(self._drive.download_text(file_id))
        return {
            "status": "OK",
            "message": "dept_config.json 저장 완료",
            "file_id": file_id,
            "dept_count": len(stored),
            "active_dept_count": _active_count(stored),
            "modified_time": meta.get("modifiedTime"),
            "departments": stored,
        }


def refresh_departments_from_drive() -> dict:
    """
    Drive 를 인증/조회해 dept_config.json 의 departments 로 로컬 캐시를 갱신합니다.
    (Drive 폴더는 건드리지 않습니다. 인증/Drive 오류는 예외로 전파됩니다.)
    반환: 갱신된 캐시 dict.
    """
    service = GoogleDriveService()
    creds = service.authenticate()
    service.save_token(creds)
    service.build_drive(creds)
    config = DeptConfigService(service).read()
    return save_cache(config["departments"], "google_drive_dept_config", config["file_id"])


def get_departments_for_tree() -> dict:
    """
    화면 트리용 부서 데이터를 돌려줍니다. (캐시 우선)
    - 캐시가 있으면 캐시 사용 (source=cache)
    - 없으면 Drive 에서 읽어 캐시 생성 (source=google_drive_refreshed)
    - Drive 실패 + 캐시 없음 → DeptConfigError(step=load_departments)
    반환: {source, cached_at, dept_count, active_dept_count, departments}
    """
    cache = load_departments_from_cache()
    source = "cache"
    if not cache:
        try:
            cache = refresh_departments_from_drive()
        except DeptConfigError:
            raise
        except Exception as e:
            _log(f"[departments] 트리 로드 실패: {type(e).__name__}: {e}")
            raise DeptConfigError(
                "부서 트리 데이터를 불러올 수 없습니다.",
                step="load_departments",
                hint="관리자 > Google Drive 동기화에서 Drive 부서 JSON을 불러오거나 저장해주세요.",
            )
        source = "google_drive_refreshed"

    return {
        "source": source,
        "cached_at": cache.get("cached_at"),
        "dept_count": cache.get("dept_count"),
        "active_dept_count": cache.get("active_dept_count"),
        "departments": cache.get("departments", []),
    }
