import os
import re
import json

import httpx
import openai
from openai import (
    OpenAI,
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    BadRequestError,
    RateLimitError,
)

# OpenAI 공통 LLM 서비스입니다.
# JD 추천(jd_recommend_service)과 이력서 분석(ai_agent_service)이 같은 클라이언트/모델/에러
# 처리를 공유합니다.
#
# - .env 의 OPENAI_API_KEY / OPENAI_MODEL 을 사용합니다. (모델 기본값 gpt-4.1-mini)
# - API key 값 자체는 로그/응답에 출력하지 않습니다. (존재 여부/길이만, 그리고 에러 메시지는 마스킹)
# - prompt(이력서 원문 포함 가능) 전체와 raw response 전체를 로그/응답에 노출하지 않습니다.
#
# 중요(SSL): 이 프로젝트는 main.py 에서 사내 forti CA 만 가리키도록 SSL_CERT_FILE 을 설정합니다.
#   httpx(openai SDK) 기본 verify 는 SSL_CERT_FILE 을 따르므로, 공개 CA 로 서명된 api.openai.com
#   인증서 검증에 실패해 APIConnectionError 가 납니다. (curl 은 시스템 공개 CA 번들을 써서 성공)
#   -> OpenAI 호출 전용 httpx 클라이언트는 공개 CA 번들(certifi)로 검증해 curl 과 동일하게 동작시킵니다.

DEFAULT_MODEL = "gpt-4.1-mini"

# certifi(공개 CA 번들). 없으면 httpx 기본값(True)으로 fallback.
try:
    import certifi
    _CA_BUNDLE = certifi.where()
except Exception:
    _CA_BUNDLE = None

_http_client = None  # 공개 CA 로 검증하는 httpx 클라이언트(재사용)


def _log(message: str) -> None:
    print(f"[llm] {message}", flush=True)


class OpenAILLMError(Exception):
    """OpenAI 호출/파싱 실패. (라우터/서비스에서 step/error_message/hint JSON 으로 변환)"""

    def __init__(self, message: str, step: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.step = step
        self.hint = hint


def get_model() -> str:
    return os.getenv("OPENAI_MODEL") or DEFAULT_MODEL


def api_key_present() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def log_llm_config() -> None:
    """provider/SDK 버전/키 존재여부/길이/모델만 로그로 남깁니다. (키 값은 절대 출력 안 함)"""
    key = os.getenv("OPENAI_API_KEY")
    _log(f"openai package version = {openai.__version__}")
    _log("provider = openai")
    _log(f"OPENAI_API_KEY exists = {bool(key)}")
    if key:
        _log(f"OPENAI_API_KEY length = {len(key)}")
    _log(f"OPENAI_MODEL = {get_model()}")


def _mask(text) -> str:
    """로그용: API key 값이나 sk- 형태 토큰을 마스킹합니다."""
    t = str(text)
    key = os.getenv("OPENAI_API_KEY")
    if key and key in t:
        t = t.replace(key, "***")
    t = re.sub(r"sk-[A-Za-z0-9_\-]{6,}", "sk-***", t)
    return t


def _require_api_key() -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise OpenAILLMError(
            "OPENAI_API_KEY가 설정되어 있지 않습니다.", "openai_api_key_missing",
            ".env 파일에 OPENAI_API_KEY를 설정한 뒤 서버를 재시작해주세요.",
        )
    return key


def _get_http_client() -> httpx.Client:
    global _http_client
    if _http_client is None:
        verify = _CA_BUNDLE if _CA_BUNDLE else True
        _http_client = httpx.Client(verify=verify, timeout=httpx.Timeout(60.0))
    return _http_client


def get_openai_client() -> OpenAI:
    """OpenAI 클라이언트를 생성합니다. (공개 CA 번들로 검증하는 httpx 클라이언트 사용)"""
    return OpenAI(api_key=_require_api_key(), http_client=_get_http_client())


def _classify_error(e: Exception):
    """OpenAI SDK 예외를 step/메시지로 정확히 분류합니다. (모델/요청 오류를 network 로 오분류하지 않음)"""
    if isinstance(e, AuthenticationError):
        return "openai_auth_failed", "OpenAI 인증에 실패했습니다."
    if isinstance(e, PermissionDeniedError):
        return "openai_permission_denied", "OpenAI 접근 권한이 없습니다."
    if isinstance(e, NotFoundError):
        return "openai_model_invalid", "OPENAI_MODEL 이 올바르지 않거나 접근할 수 없습니다."
    if isinstance(e, RateLimitError):
        return "openai_rate_limited", "OpenAI 호출 한도를 초과했습니다."
    if isinstance(e, BadRequestError):
        msg = str(e).lower()
        if "model" in msg:
            return "openai_model_invalid", "OPENAI_MODEL 설정이 올바르지 않습니다."
        return "openai_bad_request", "OpenAI 요청 형식이 올바르지 않습니다."
    if isinstance(e, (APITimeoutError, APIConnectionError)):
        return "openai_network_failed", "OpenAI 네트워크 연결에 실패했습니다."
    return "openai_call_failed", "OpenAI API 호출 중 오류가 발생했습니다."


def _log_call_error(e: Exception) -> None:
    _log("openai call failed")
    _log(f"error type = {type(e).__name__}")
    _log(f"error message = {_mask(str(e))}")
    _log(f"error repr = {_mask(repr(e))}")


def _extract_text_responses(response) -> str:
    """Responses API 응답에서 텍스트를 안전하게 추출합니다. (output_text 우선)"""
    text = getattr(response, "output_text", None)
    if text:
        return text
    parts = []
    try:
        for item in getattr(response, "output", []) or []:
            for c in getattr(item, "content", []) or []:
                t = getattr(c, "text", None)
                if t:
                    parts.append(t)
    except Exception:
        return ""
    return "".join(parts)


def call_openai_text(prompt: str) -> str:
    """
    OpenAI 를 호출해 응답 텍스트를 반환합니다.
    1) Responses API 사용 -> 2) 실패/빈응답이면 Chat Completions 로 fallback.
    실패 시 실제 원인에 맞는 step 으로 OpenAILLMError.
    """
    client = get_openai_client()
    model = get_model()
    hint = "OPENAI_API_KEY, OPENAI_MODEL(/v1/models 목록에 있는지), 네트워크 상태를 확인해주세요."

    # 1) Responses API
    try:
        resp = client.responses.create(model=model, input=prompt)
        text = _extract_text_responses(resp)
        if text and text.strip():
            return text
        _log("responses api returned empty; trying chat.completions fallback")
    except Exception as e:
        _log_call_error(e)
        _log("responses api call failed, trying chat.completions fallback")

    # 2) Chat Completions fallback
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that returns only valid JSON."},
                {"role": "user", "content": prompt},
            ],
        )
        text = resp.choices[0].message.content if resp.choices else ""
    except Exception as e:
        _log_call_error(e)
        step, msg = _classify_error(e)
        raise OpenAILLMError(msg, step, hint) from e

    if not text or not text.strip():
        raise OpenAILLMError(
            "OpenAI 응답이 비어 있습니다.", "openai_response_empty",
            "잠시 후 다시 시도하거나 프롬프트를 확인해주세요.",
        )
    return text


def strip_json_code_block(text: str) -> str:
    """```json 코드블록/앞뒤 텍스트를 제거하고 JSON 본문만 남깁니다."""
    t = (text or "").strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    t = t.strip()
    # 본문 앞뒤에 다른 텍스트가 섞여 있으면 첫 '{' ~ 마지막 '}' 만 추출
    if not t.startswith("{"):
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            t = m.group(0)
    return t


def call_openai_json(prompt: str) -> dict:
    """OpenAI 응답을 JSON(dict)으로 파싱해 반환합니다. 파싱 실패 시 openai_response_parse_failed."""
    text = call_openai_text(prompt)
    cleaned = strip_json_code_block(text)
    try:
        parsed = json.loads(cleaned)
    except Exception as e:
        raise OpenAILLMError(
            "OpenAI 응답을 JSON으로 파싱하지 못했습니다.", "openai_response_parse_failed",
            "LLM 프롬프트의 JSON 반환 지시와 응답 파싱 로직을 확인해주세요.",
        ) from e
    if not isinstance(parsed, dict):
        raise OpenAILLMError(
            "OpenAI 응답이 예상한 JSON 객체 형식이 아닙니다.", "openai_response_parse_failed",
            "LLM 프롬프트의 JSON 반환 지시를 확인해주세요.",
        )
    return parsed


def test_openai_connection() -> dict:
    """개발용 smoke test. (API 로 노출하지 않음)"""
    return call_openai_json('Return only JSON: {"ok": true}')


if __name__ == "__main__":
    # 로컬 디버깅: uv run python -m app.services.openai_llm_service
    log_llm_config()
    try:
        print("[llm] smoke test result =", test_openai_connection())
    except OpenAILLMError as e:
        print(f"[llm] smoke test failed: step={e.step} message={e.message} hint={e.hint}")
