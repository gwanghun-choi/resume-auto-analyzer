from typing import List, Dict, Any

from app.services.openai_llm_service import call_openai_json

# AiAgentService 는 이력서 텍스트를 OpenAI 로 분석하는 서비스입니다.
# (기존 LangGraph + Gemini 파이프라인을 OpenAI 호출로 교체. 반환 JSON 구조는 그대로 유지하여
#  resume_analysis_service._run_ai + MatchingService 가 변경 없이 동작합니다.)
#
# 반환 dict 구조(기존과 동일):
#   candidate_summary, extracted_skills, career_summary, strengths, weaknesses,
#   recommendation, ai_judgment_score (0~10 정수)


def _build_prompt(resume_text: str, position: str,
                  required_skills: List[str], preferred_skills: List[str]) -> str:
    required = ", ".join(required_skills or [])
    preferred = ", ".join(preferred_skills or [])
    return (
        "당신은 전문 채용 담당자이자 기술 면접관입니다.\n"
        f"제공된 이력서 텍스트를 분석하여 지원 포지션({position})에 적합한지 한국어로 평가하세요.\n\n"
        "분석 항목:\n"
        "1. 후보자 요약 (candidate_summary)\n"
        "2. 이력서에서 추출된 모든 기술 스택 (extracted_skills)\n"
        "3. 주요 경력 사항 요약 (career_summary)\n"
        "4. 강점 (strengths)\n"
        "5. 약점/보완점 (weaknesses)\n"
        "6. 채용 추천 여부 및 종합 의견 (recommendation)\n"
        "7. AI 종합 판단 점수 (ai_judgment_score): 0~10 사이의 정수 (전체 적합성)\n\n"
        "반드시 아래 JSON 형식으로만 응답하세요. 다른 설명/마크다운은 생략합니다.\n"
        "{\n"
        '  "candidate_summary": "...",\n'
        '  "extracted_skills": ["skill1", "skill2"],\n'
        '  "career_summary": "...",\n'
        '  "strengths": ["...", "..."],\n'
        '  "weaknesses": ["...", "..."],\n'
        '  "recommendation": "...",\n'
        '  "ai_judgment_score": 8\n'
        "}\n\n"
        f"[필수 기술]\n{required}\n\n"
        f"[우대 기술]\n{preferred}\n\n"
        f"[이력서 내용]\n{resume_text}"
    )


class AiAgentService:
    def analyze(self, resume_text: str, position: str,
                required_skills: List[str], preferred_skills: List[str]) -> Dict[str, Any]:
        """OpenAI 를 사용해 이력서를 분석하고 파싱된 결과 dict 를 반환합니다."""
        prompt = _build_prompt(resume_text, position, required_skills, preferred_skills)
        # 실패는 OpenAILLMError 로 전파됩니다. (호출처에서 파일 단위 실패로 처리)
        return call_openai_json(prompt)
