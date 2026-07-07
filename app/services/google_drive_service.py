import json
import os
from pathlib import Path
from typing import Optional

import httplib2
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload, MediaFileUpload

# Docker/회사망 기본 CA 번들 (curl 이 신뢰하는 시스템 번들과 동일)
DEFAULT_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


def _ca_bundle() -> str:
    """googleapiclient/httplib2 가 사용할 CA 번들 경로. (SSL_CERT_FILE > REQUESTS_CA_BUNDLE > 기본값)"""
    return (
        os.getenv("SSL_CERT_FILE")
        or os.getenv("REQUESTS_CA_BUNDLE")
        or DEFAULT_CA_BUNDLE
    )


def _log(message: str) -> None:
    """단계별 진행 상황을 터미널에 출력합니다. (uvicorn 로그와 함께 보입니다)"""
    print(f"[drive] {message}", flush=True)

# GoogleDriveService 는 Google Drive 연동을 담당하는 서비스입니다. (Spring 의 @Service 와 동일 역할)
#
# 지금은 "연결 확인 + 기본 폴더 생성" 까지만 담당합니다.
# 나중에 실제 이력서 업로드/이동(completed/failed) 로직이 추가될 때
# 이 클래스 내부에 메서드만 더하면 라우터/화면은 거의 손대지 않아도 되도록 분리해 두었습니다.

# 프로젝트 루트 경로 (이 파일 기준: app/services -> app -> 루트)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Google OAuth 파일 경로는 app/core/paths.py 에서 .env(GOOGLE_CREDENTIALS_PATH /
# GOOGLE_TOKEN_PATH) 기준으로 계산합니다. (운영=절대경로, 개발=루트 fallback)
# 기존 이름(CREDENTIALS_PATH/TOKEN_PATH)을 그대로 사용해 다른 모듈 import 는 바꾸지 않습니다.
from app.core.paths import GOOGLE_CREDENTIALS_PATH as CREDENTIALS_PATH
from app.core.paths import GOOGLE_TOKEN_PATH as TOKEN_PATH

# 폴더 생성/조회에 필요한 권한 범위입니다.
# (이미 만들어진 폴더를 이름으로 조회해 재사용하려면 drive 범위가 필요합니다.)
SCOPES = ["https://www.googleapis.com/auth/drive"]

# 생성할 기본 폴더 구조
ROOT_FOLDER_NAME = "resume-demo-root"
# config 는 dept_config.json(부서 데이터 원천)을 보관하는 설정 폴더입니다.
SUB_FOLDER_NAMES = ["config", "inbox", "completed", "failed"]

# Google Drive 에서 "폴더" 를 나타내는 MIME 타입
MIME_FOLDER = "application/vnd.google-apps.folder"


class DriveConfigError(Exception):
    """
    credentials.json / token.json 설정 문제로 인증을 진행할 수 없을 때 발생합니다.
    (라우터에서 이 예외를 잡아 원인 메시지를 JSON 으로 돌려줍니다.)
    """


class GoogleDriveService:
    def __init__(self):
        # build_drive() 가 호출되기 전까지는 Drive 클라이언트가 없습니다.
        # (인증 → 토큰 저장 → build → 폴더 생성 순서를 라우터가 단계별로 호출합니다)
        self._service = None
        # 토큰이 새로 갱신/발급되어 저장이 필요한지 여부.
        # (기존 유효 토큰을 그대로 사용한 경우 False → save_token 을 생략해 오해성 에러를 막음)
        self._token_dirty = False

    @property
    def token_dirty(self) -> bool:
        """authenticate() 결과 token.json 을 다시 저장해야 하는지 여부."""
        return self._token_dirty

    def authenticate(self) -> Credentials:
        """
        [step: oauth] OAuth 인증 정보를 준비합니다. (token.json 저장은 save_token 에서 별도 수행)
        - token.json 이 있고 유효하면 그대로 재사용합니다. (재로그인 안 함)
        - 만료됐고 refresh_token 이 있으면 갱신합니다. (성공 시에만 save_token 으로 덮어씀)
        - 갱신 실패 시 기존 token.json 은 삭제하지 않고 보존하며 명확한 에러를 던집니다.
        - 토큰이 없거나 refresh_token 이 없으면 credentials.json 으로 최초 로그인 플로우를 수행합니다.
        """
        _log(f"cwd                     = {os.getcwd()}")
        _log(f"PROJECT_ROOT            = {PROJECT_ROOT}")
        _log(f"GOOGLE_CREDENTIALS_PATH = {CREDENTIALS_PATH}")
        _log(f"GOOGLE_TOKEN_PATH       = {TOKEN_PATH}")
        _log(f"credentials exists      = {CREDENTIALS_PATH.exists()}")
        _log(f"token exists            = {TOKEN_PATH.exists()}")

        creds = self._load_existing_token()
        _log(f"creds.valid       = {bool(creds and creds.valid)}")
        _log(f"creds.expired     = {bool(creds and creds.expired)}")
        _log(f"has_refresh_token = {bool(creds and creds.refresh_token)}")

        # 유효한 토큰이 있으면 재인증하지 않고 그대로 사용합니다. (저장 불필요)
        if creds and creds.valid:
            self._token_dirty = False
            _log("기존 token 이 유효합니다 → 그대로 사용 (저장 생략)")
            return creds

        # 만료됐지만 refresh_token 이 있으면 갱신을 시도합니다.
        # access token 만료는 정상 상황이므로 token.json 을 삭제하지 않습니다.
        if creds and creds.expired and creds.refresh_token:
            _log("refresh start")
            try:
                creds.refresh(Request())
            except Exception as e:
                # 중요: refresh 실패 시 기존 token.json 을 삭제하지 않습니다. (refresh_token 보존)
                _log("refresh failed")
                _log("existing token.json preserved")
                _log("manual re-authentication may be required")
                raise DriveConfigError(
                    "refresh_token 으로 access token 갱신에 실패했습니다. "
                    "Google 계정 권한이 제거되었거나 OAuth client/scopes 가 변경되었을 수 있습니다. "
                    "기존 token.json 은 삭제하지 않았습니다."
                ) from e
            # 갱신했으니 token.json 을 다시 저장해야 합니다.
            self._token_dirty = True
            _log("refresh success")
            return creds

        # 토큰이 없거나 refresh_token 이 없으면 최초 로그인 플로우를 수행합니다.
        # (기존 token.json 을 자동 삭제하지 않습니다. save_token 으로 성공 시에만 덮어씀)
        self._validate_credentials_file()
        _log("credentials.json 로딩 성공 (Desktop app 'installed' 형식 확인)")
        _log("OAuth 인증 시작 (터미널에 출력되는 URL 을 Windows 브라우저에서 여세요)")
        creds = self._run_login_flow()
        # 최초 인증으로 새 토큰을 발급받았으니 저장이 필요합니다.
        self._token_dirty = True
        _log("OAuth 인증 완료 (브라우저 로그인/토큰 교환 성공)")
        return creds

    def save_token(self, creds: Credentials) -> None:
        """
        [step: token_save] token.json 을 GOOGLE_TOKEN_PATH 로 저장합니다.
        - parent 디렉토리가 없으면 생성합니다. (예: /app/secrets/google)
        - atomic save 후 실제 생성 여부를 검증합니다. (인증은 됐는데 파일이 안 생기면 명확한 에러)
        """
        _log(f"token 저장 경로 = {TOKEN_PATH}")
        # parent 디렉토리 보장 (Docker /app/secrets/google 처럼 폴더가 없을 수 있음)
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        # atomic save: 임시 파일에 먼저 쓰고 os.replace 로 교체합니다.
        # (저장 중 오류가 나도 기존 token.json 이 깨지지 않도록)
        tmp_path = TOKEN_PATH.with_name(TOKEN_PATH.name + ".tmp")
        tmp_path.write_text(creds.to_json(), encoding="utf-8")
        os.replace(tmp_path, TOKEN_PATH)
        if not TOKEN_PATH.exists():
            raise DriveConfigError(
                f"OAuth 인증은 완료됐지만 token.json 이 생성되지 않았습니다: {TOKEN_PATH}. "
                "GOOGLE_TOKEN_PATH 디렉토리의 쓰기 권한을 확인하고 다시 시도하세요."
            )
        _log(f"token saved to {TOKEN_PATH} (exists after save = {TOKEN_PATH.exists()})")

    def build_drive(self, creds: Credentials) -> None:
        """
        [step: drive_build] Drive API v3 클라이언트를 생성합니다.

        Docker/회사망에서는 httplib2 가 시스템 CA 번들을 제대로 쓰지 못해 self-signed
        (회사 Root CA) 체인 검증에 실패합니다. 그래서 ca_certs 를 명시한 httplib2.Http +
        AuthorizedHttp 로 build 해 curl 과 동일한 CA 번들을 사용하게 합니다.
        (모든 Drive 기능이 이 GoogleDriveService 인스턴스를 공유하므로 CA 설정이 일원화됩니다.)
        """
        _log("drive service build start")
        ca_certs = _ca_bundle()
        _log(f"using CA bundle = {ca_certs}")
        _log(f"SSL_CERT_FILE = {os.getenv('SSL_CERT_FILE')}")
        _log(f"REQUESTS_CA_BUNDLE = {os.getenv('REQUESTS_CA_BUNDLE')}")
        http = httplib2.Http(ca_certs=ca_certs)
        authed_http = AuthorizedHttp(creds, http=http)
        _log("httplib2 custom ca_certs enabled = True")
        self._service = build("drive", "v3", http=authed_http, cache_discovery=False)
        _log("drive service build success")
        _log("Drive service build 성공")

    def _load_existing_token(self) -> Optional[Credentials]:
        """
        token.json 을 읽어옵니다. 파일이 없으면 None 을 반환합니다.
        파일이 깨졌어도 자동 삭제하지 않고 None 을 반환합니다.
        (성공적으로 재인증되면 save_token 이 atomic 하게 덮어씁니다.)
        """
        if not TOKEN_PATH.exists():
            _log("token loaded = false (token.json 없음 → 최초 인증 필요)")
            return None
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            _log("token loaded = true")
            return creds
        except (ValueError, json.JSONDecodeError) as e:
            # 깨졌거나 형식이 잘못된 토큰입니다. 자동 삭제하지 않고 None 을 반환합니다. (재인증 시 덮어씀)
            _log(f"token loaded = false (token.json 형식 오류, 삭제하지 않음): {e}")
            return None

    def _run_login_flow(self) -> Credentials:
        """
        credentials.json 을 검증한 뒤 최초 로그인 플로우를 수행합니다.

        WSL 환경 대응:
        - open_browser=False 로 브라우저 자동 실행(xdg-open)을 시도하지 않습니다.
        - 대신 인증 URL 을 터미널에 출력하고, 사용자가 Windows 브라우저에서 직접 열도록 합니다.
        - 로컬 콜백 서버(host=localhost, port=0)가 리다이렉트를 받아 토큰 교환까지 처리합니다.
        """
        self._validate_credentials_file()
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
        # 3) 인증 URL 을 터미널 로그에 명확히 출력합니다. ({url} 는 라이브러리가 치환)
        prompt = (
            "\n========================================================\n"
            "아래 URL을 Windows 브라우저에서 열어 Google 인증을 완료하세요:\n"
            "{url}\n"
            "========================================================\n"
        )
        # 2) WSL 에서는 반드시 open_browser=False 로 자동 실행을 끕니다.
        return flow.run_local_server(
            host="localhost",
            port=0,
            open_browser=False,
            authorization_prompt_message=prompt,
        )

    def _validate_credentials_file(self) -> None:
        """
        credentials.json 이 Desktop app(OAuth) 형식인지 검증합니다.
        - 파일이 없으면 안내
        - 최상위 key 가 "web" 이면 형식이 잘못됐다고 명확히 안내
        - 최상위 key 가 "installed" 가 아니면 안내
        """
        if not CREDENTIALS_PATH.exists():
            raise DriveConfigError(
                f"Google OAuth credentials.json 파일을 찾을 수 없습니다: {CREDENTIALS_PATH}. "
                "GOOGLE_CREDENTIALS_PATH 경로와 파일 존재 여부를 확인해주세요."
            )

        try:
            data = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise DriveConfigError(
                f"credentials.json 을 읽을 수 없습니다(JSON 형식 오류): {e}"
            )

        if "web" in data:
            raise DriveConfigError(
                "credentials.json 이 'web' 형식입니다. "
                "Google Cloud Console 에서 OAuth 클라이언트 유형을 "
                "'데스크톱 앱(Desktop app)' 으로 새로 발급받아 최상위 key 가 "
                "'installed' 인 파일로 교체하세요."
            )
        if "installed" not in data:
            raise DriveConfigError(
                "credentials.json 형식을 인식할 수 없습니다. "
                "Desktop app 형식(최상위 key 'installed')이어야 합니다. "
                f"현재 최상위 key: {list(data.keys())}"
            )

    def find_folder(self, name: str, parent_id: Optional[str] = None) -> Optional[str]:
        """같은 부모 아래에서 이름이 일치하는 폴더의 ID 를 찾습니다. 없으면 None."""
        query = [
            f"name = '{name}'",
            f"mimeType = '{MIME_FOLDER}'",
            "trashed = false",
        ]
        if parent_id:
            query.append(f"'{parent_id}' in parents")

        result = (
            self._service.files()
            .list(q=" and ".join(query), spaces="drive", fields="files(id, name)")
            .execute()
        )
        files = result.get("files", [])
        return files[0]["id"] if files else None

    def get_or_create_folder(self, name: str, parent_id: Optional[str] = None) -> str:
        """
        폴더를 조회하거나 없으면 생성합니다.
        같은 부모 아래에 동일 이름 폴더가 있으면 새로 만들지 않고 기존 ID 를 재사용합니다.
        """
        existing = self.find_folder(name, parent_id)
        if existing:
            return existing

        metadata = {"name": name, "mimeType": MIME_FOLDER}
        if parent_id:
            metadata["parents"] = [parent_id]
        folder = self._service.files().create(body=metadata, fields="id").execute()
        return folder["id"]

    def ensure_project_folders(self) -> dict:
        """
        [step: folder_create] resume-demo-root 와 그 하위(inbox/completed/failed) 폴더를 보장합니다.
        반환: {"root_id": ..., "folders": {"inbox": ..., "completed": ..., "failed": ...}}
        """
        root_id = self.get_or_create_folder(ROOT_FOLDER_NAME)
        _log(f"폴더 확인/생성: {ROOT_FOLDER_NAME} -> {root_id}")
        folders = {}
        for name in SUB_FOLDER_NAMES:
            folder_id = self.get_or_create_folder(name, root_id)
            _log(f"폴더 확인/생성: {ROOT_FOLDER_NAME}/{name} -> {folder_id}")
            folders[name] = folder_id
        _log("폴더 생성/조회 성공")
        return {"root_id": root_id, "folders": folders}

    # ----- 파일(텍스트/JSON) 입출력 -----
    # dept_config.json 같은 설정 파일을 Drive 에 저장/조회하기 위한 헬퍼들입니다.

    def find_file(self, name: str, parent_id: Optional[str] = None) -> Optional[dict]:
        """같은 부모 아래에서 이름이 일치하는 (폴더가 아닌) 파일 메타를 찾습니다. 없으면 None."""
        query = [
            f"name = '{name}'",
            f"mimeType != '{MIME_FOLDER}'",
            "trashed = false",
        ]
        if parent_id:
            query.append(f"'{parent_id}' in parents")

        result = (
            self._service.files()
            .list(q=" and ".join(query), spaces="drive", fields="files(id, name, modifiedTime)")
            .execute()
        )
        files = result.get("files", [])
        return files[0] if files else None

    def download_text(self, file_id: str) -> str:
        """파일 본문을 텍스트로 다운로드합니다."""
        data = self._service.files().get_media(fileId=file_id).execute()
        return data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else str(data)

    def create_text_file(self, name: str, parent_id: str, content: str,
                         mime_type: str = "application/json") -> str:
        """텍스트 본문으로 파일을 생성하고 file_id 를 반환합니다."""
        metadata = {"name": name, "parents": [parent_id]} if parent_id else {"name": name}
        media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=mime_type, resumable=False)
        created = (
            self._service.files()
            .create(body=metadata, media_body=media, fields="id")
            .execute()
        )
        return created["id"]

    def update_text_file(self, file_id: str, content: str,
                         mime_type: str = "application/json") -> None:
        """기존 파일 본문을 텍스트로 교체합니다."""
        media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=mime_type, resumable=False)
        self._service.files().update(fileId=file_id, media_body=media).execute()

    def get_file_metadata(self, file_id: str, fields: str = "id, name, modifiedTime") -> dict:
        """파일 메타데이터(기본: id/name/modifiedTime)를 조회합니다."""
        return self._service.files().get(fileId=file_id, fields=fields).execute()

    # ----- 이력서 업로드용 헬퍼 -----

    def create_folder_if_not_exists(self, parent_folder_id: str, folder_name: str) -> str:
        """부모 아래에 같은 이름 폴더가 있으면 재사용, 없으면 생성한 뒤 folder_id 를 반환합니다."""
        return self.get_or_create_folder(folder_name, parent_folder_id)

    def _list_child_file_names(self, parent_folder_id: str) -> set:
        """부모 폴더 아래의 (폴더가 아닌) 파일 이름 집합을 반환합니다."""
        result = (
            self._service.files()
            .list(
                q=f"'{parent_folder_id}' in parents and mimeType != '{MIME_FOLDER}' and trashed = false",
                spaces="drive",
                fields="files(name)",
            )
            .execute()
        )
        return {f["name"] for f in result.get("files", [])}

    def make_unique_file_name(self, parent_folder_id: str, file_name: str,
                              reserved: set = None) -> str:
        """
        같은 부모 아래에 동일 파일명이 있으면 덮어쓰지 않도록 고유 이름을 만듭니다.
        (예: 홍길동.pdf -> 홍길동_1.pdf -> 홍길동_2.pdf)
        reserved 는 아직 Drive 에 안 올라간 같은 요청 내 이름 충돌도 막기 위한 집합입니다.
        """
        existing = self._list_child_file_names(parent_folder_id)
        if reserved:
            existing = existing | reserved
        if file_name not in existing:
            return file_name

        stem, dot, ext = file_name.rpartition(".")
        base = stem if dot else file_name
        suffix = f".{ext}" if dot else ""
        i = 1
        while f"{base}_{i}{suffix}" in existing:
            i += 1
        return f"{base}_{i}{suffix}"

    def upload_file_to_folder(self, local_file_path: str, parent_folder_id: str,
                              file_name: str, mime_type: str = None) -> str:
        """로컬 파일을 지정한 부모 폴더 아래에 업로드하고 file_id 를 반환합니다."""
        metadata = {"name": file_name, "parents": [parent_folder_id]}
        media = MediaFileUpload(local_file_path, mimetype=mime_type, resumable=False)
        created = (
            self._service.files()
            .create(body=metadata, media_body=media, fields="id")
            .execute()
        )
        return created["id"]

    def find_file_or_folder_by_name(self, parent_folder_id: str, name: str):
        """부모 아래에서 이름이 일치하는 항목(파일/폴더)을 찾습니다. 없으면 None."""
        result = (
            self._service.files()
            .list(
                q=f"name = '{name}' and '{parent_folder_id}' in parents and trashed = false",
                spaces="drive",
                fields="files(id, name, mimeType)",
            )
            .execute()
        )
        files = result.get("files", [])
        return files[0] if files else None

    def _list_child_folder_names(self, parent_folder_id: str) -> set:
        """부모 폴더 아래의 (폴더인) 하위 폴더 이름 집합을 반환합니다."""
        result = (
            self._service.files()
            .list(
                q=f"'{parent_folder_id}' in parents and mimeType = '{MIME_FOLDER}' and trashed = false",
                spaces="drive",
                fields="files(name)",
            )
            .execute()
        )
        return {f["name"] for f in result.get("files", [])}

    def make_unique_folder_name(self, parent_folder_id: str, folder_name: str) -> str:
        """
        같은 부모 아래에 동일 폴더명이 있으면 _1, _2 를 붙여 고유 이름을 만듭니다.
        (upload_id 가 초 단위라 이론상 중복 가능 → 항상 unique 보장)
        """
        existing = self._list_child_folder_names(parent_folder_id)
        if folder_name not in existing:
            return folder_name
        i = 1
        while f"{folder_name}_{i}" in existing:
            i += 1
        return f"{folder_name}_{i}"

    def download_file(self, file_id: str, local_path: str) -> None:
        """Drive 파일을 로컬 경로로 다운로드합니다."""
        data = self._service.files().get_media(fileId=file_id).execute()
        with open(local_path, "wb") as out:
            out.write(data if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8"))

    def download_bytes(self, file_id: str) -> bytes:
        """Drive 파일 본문을 바이트로 다운로드합니다. (원본 파일 다운로드 API 용 — docx/pdf 등 일반 파일)"""
        data = self._service.files().get_media(fileId=file_id).execute()
        return data if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8")

    def move_file_to_folder(self, file_id: str, from_folder_id: str, to_folder_id: str,
                            new_name: str = None) -> None:
        """
        파일을 다른 폴더로 '이동' 합니다. (삭제/재업로드가 아니라 parent 변경)
        대상 폴더에 동일 이름이 있어 unique name 으로 바꿔야 하면 new_name 을 함께 지정합니다.
        """
        body = {"name": new_name} if new_name else {}
        self._service.files().update(
            fileId=file_id,
            addParents=to_folder_id,
            removeParents=from_folder_id,
            body=body,
            fields="id, parents",
        ).execute()

    # ----- 빈 업로드 폴더 정리 (분석 후 비어버린 inbox upload 폴더 전용) -----

    def list_children(self, folder_id: str) -> list:
        """폴더 바로 아래의 자식(파일/폴더) 목록을 반환합니다."""
        result = (
            self._service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                spaces="drive",
                fields="files(id, name, mimeType)",
            )
            .execute()
        )
        return result.get("files", [])

    def is_folder_empty(self, folder_id: str) -> bool:
        """폴더 내부에 파일/폴더가 하나도 없으면 True."""
        return len(self.list_children(folder_id)) == 0

    def trash_file_or_folder(self, file_or_folder_id: str) -> None:
        """항목을 휴지통(trash)으로 보냅니다. (영구 삭제 아님)"""
        self._service.files().update(
            fileId=file_or_folder_id, body={"trashed": True}, fields="id, trashed"
        ).execute()

    def cleanup_empty_folder(self, folder_id: str) -> dict:
        """
        폴더가 '비어 있을 때만' 휴지통으로 정리합니다. (부서 폴더에는 쓰지 마세요)
        반환: {"was_empty": bool, "cleanup_status": "TRASHED" | "SKIPPED_NOT_EMPTY"}
        """
        if not self.is_folder_empty(folder_id):
            return {"was_empty": False, "cleanup_status": "SKIPPED_NOT_EMPTY"}
        self.trash_file_or_folder(folder_id)
        return {"was_empty": True, "cleanup_status": "TRASHED"}


def build_authenticated_drive() -> "GoogleDriveService":
    """
    인증 + service build 까지 끝난 GoogleDriveService 를 반환하는 공통 헬퍼입니다.
    (기존 authenticate/save_token/build_drive 로직을 그대로 재사용합니다. 새 인증 로직이 아닙니다.)
    실패 시 DriveConfigError(또는 기타 예외)를 던집니다. — 공고 폴더 생성/공고 업로드/공고 분석에서 공용.
    """
    service = GoogleDriveService()
    if not TOKEN_PATH.exists():
        raise DriveConfigError("token.json이 없어 Google Drive 인증이 필요합니다.")
    creds = service.authenticate()
    if service.token_dirty:
        service.save_token(creds)
    service.build_drive(creds)
    return service
