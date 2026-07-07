import re

from app.services.openai_llm_service import call_openai_json, OpenAILLMError

# 추천JD 서비스: 선택 부서명/포지션명을 기반으로 OpenAI 에게 JD 초안을 생성합니다.
# (공통 OpenAI LLM 서비스 app/services/openai_llm_service.py 를 사용합니다.)
#
# - DB 저장은 하지 않습니다. 결과는 프론트 입력란 채우기 용도로만 반환합니다.
# - 실패는 OpenAILLMError(step/message/hint) 로 전파합니다. (라우터에서 JSON 에러로 변환)


def _to_list(value) -> list:
    """리스트가 아니면 줄바꿈/쉼표 기준으로 보정합니다."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    parts = re.split(r"[\n,]", str(value))
    return [p.strip() for p in parts if p.strip()]


def _build_prompt(dept_name: str, position_title: str) -> str:
    return (
        "당신은 HR 채용 JD 작성 전문가입니다.\n"
        "아래 정보를 기반으로 채용 포지션의 JD 초안을 작성하세요.\n\n"
        f"부서명: {dept_name}\n"
        f"포지션명: {position_title}\n\n"
        "요구사항:\n"
        "1. 한국어로 작성합니다.\n"
        "2. 실무자가 바로 검토할 수 있는 수준으로 작성합니다.\n"
        "3. description은 3~5문장입니다.\n"
        "4. required_skills는 4~8개 배열입니다.\n"
        "5. preferred_skills는 3~6개 배열입니다.\n"
        "6. 과장된 표현은 피하고, 일반적인 채용 JD 문체로 작성합니다.\n"
        "7. 반드시 아래 JSON 형식만 반환합니다. 다른 설명은 생략합니다.\n\n"
        "반환 형식:\n"
        "{\n"
        '  "description": "...",\n'
        '  "required_skills": ["...", "..."],\n'
        '  "preferred_skills": ["...", "..."]\n'
        "}"
    )


def recommend_jd(dept_name: str, position_title: str) -> dict:
    """
    부서명/포지션명으로 JD 초안을 생성합니다.
    반환: {"description": str, "required_skills": list, "preferred_skills": list}
    실패 시 OpenAILLMError (step: openai_api_key_missing / openai_call_failed /
    openai_response_parse_failed 등).
    """
    parsed = call_openai_json(_build_prompt(dept_name, position_title))
    return {
        "description": str(parsed.get("description") or "").strip(),
        "required_skills": _to_list(parsed.get("required_skills")),
        "preferred_skills": _to_list(parsed.get("preferred_skills")),
    }
