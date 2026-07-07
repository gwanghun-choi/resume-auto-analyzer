import os
from pathlib import Path

from dotenv import load_dotenv

# Google OAuth(자격증명/토큰) 파일 경로를 한 곳에서 계산하는 공통 유틸입니다.
#
# - 운영/Docker: .env 의 GOOGLE_CREDENTIALS_PATH / GOOGLE_TOKEN_PATH(절대경로)를 사용합니다.
#     예) /app/secrets/google/credentials.json, /app/secrets/google/token.json
# - 개발: 환경변수가 없으면 프로젝트 루트의 credentials.json / token.json 으로 fallback 합니다.
# - 상대경로(secrets/google/token.json 등)는 PROJECT_ROOT 기준으로 해석합니다.
# - Path.cwd() 에 의존하지 않습니다. (실행 위치와 무관하게 동일 경로)
#
# 주의: 이 모듈은 라우터 import 시점(= main.py 의 load_dotenv() 보다 먼저)일 수 있어
#       여기서 load_dotenv() 를 직접 호출해 .env 값을 보장합니다. (idempotent)
load_dotenv()

# app/core/paths.py -> parents[2] = 프로젝트 루트
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_project_path(path_value, default_relative_path: str) -> Path:
    """
    경로 값(보통 환경변수)을 안전하게 절대경로로 해석합니다.
    - 절대경로면 그대로 사용
    - 상대경로면 PROJECT_ROOT 기준으로 해석
    - 값이 없으면 default_relative_path(PROJECT_ROOT 기준)로 fallback
    """
    if path_value:
        path = Path(path_value)
    else:
        path = PROJECT_ROOT / default_relative_path
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


# 개발 fallback 은 기존 동작과 동일하게 '프로젝트 루트' 의 파일을 사용합니다.
GOOGLE_CREDENTIALS_PATH = resolve_project_path(
    os.getenv("GOOGLE_CREDENTIALS_PATH"), "credentials.json"
)
GOOGLE_TOKEN_PATH = resolve_project_path(
    os.getenv("GOOGLE_TOKEN_PATH"), "token.json"
)
