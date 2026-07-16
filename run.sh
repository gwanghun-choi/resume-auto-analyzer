#!/bin/bash
# 로컬 개발 서버 실행. uv 가 PATH 에 없으면 기본 설치 경로를 추가합니다.
export PATH="$HOME/.local/bin:$PATH"
uv sync
uv run uvicorn app.main:app --reload
