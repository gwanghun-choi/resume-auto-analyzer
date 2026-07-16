FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# healthcheck(curl) 와 일부 패키지 빌드에 필요한 최소 패키지만 설치합니다.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 사설 Root CA 등록(선택). SSL inspection 이 있는 사내망에서만 필요합니다.
# certs/ 에 .crt 를 두면 시스템 신뢰 번들에 병합되고, 없으면 공개 CA 만 사용합니다.
# (certs/.gitkeep 덕분에 디렉토리가 비어 있어도 COPY 가 실패하지 않습니다. 실제 인증서는 커밋하지 마세요.)
COPY certs/ /usr/local/share/ca-certificates/

RUN update-ca-certificates

# 패키지 관리자(uv) 설치
RUN pip install --no-cache-dir uv

# 의존성 정의 먼저 복사 → 레이어 캐시 활용 (소스만 바뀌면 의존성 재설치 안 함)
COPY pyproject.toml uv.lock ./

# 운영용: dev 의존성 제외, lockfile 고정으로 '의존성만' 설치 (.venv 생성)
# (--no-install-project: 로컬 프로젝트는 패키지로 빌드/설치하지 않음. 앱은 `uvicorn app.main:app`
#  으로 /app 작업 디렉토리에서 직접 import 되므로 패키지 설치가 필요 없음 → src 레이아웃 불일치 회피)
RUN uv sync --frozen --no-dev --no-install-project

# 전체 소스 복사
COPY . .

# 컨테이너 내부 FastAPI 포트 (외부 노출 포트는 docker-compose.yml 에서 매핑)
EXPOSE 8000

# 운영 실행: --reload 사용하지 않음
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
