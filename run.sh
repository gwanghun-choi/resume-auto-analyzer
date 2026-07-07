#!/bin/bash
export PATH="/home/ghchoi/.local/bin:$PATH"
uv sync
uv run uvicorn app.main:app --reload
