from typing import List, Dict, Any

# MatchingService는 점수 산출 로직을 담당합니다.
# Spring Boot의 Service 클래스와 역할이 동일합니다.

class MatchingService:
    def calculate_match(
        self, 
        extracted_skills: List[str], 
        required_skills: List[str], 
        preferred_skills: List[str],
        ai_judgment_score: int
    ) -> Dict[str, Any]:
        """
        점수 계산 로직:
        1. 필수 기술 매칭: matched_required / total_required * 70
        2. 우대 기술 매칭: matched_preferred / total_preferred * 20
        3. AI 종합 판단: 0~10점
        총합: 100점 만점
        """
        
        # 대소문자 무시를 위해 소문자로 변환 및 공백 제거
        extracted_set = {s.lower().strip() for s in extracted_skills}
        
        # 필수 기술 매칭
        matched_required = []
        missing_required = []
        for skill in required_skills:
            if skill.lower().strip() in extracted_set:
                matched_required.append(skill)
            else:
                missing_required.append(skill)
        
        required_score = 0
        if required_skills:
            required_score = (len(matched_required) / len(required_skills)) * 70
            
        # 우대 기술 매칭
        matched_preferred = []
        for skill in preferred_skills:
            if skill.lower().strip() in extracted_set:
                matched_preferred.append(skill)
        
        preferred_score = 0
        if preferred_skills:
            preferred_score = (len(matched_preferred) / len(preferred_skills)) * 20
            
        # 최종 점수 계산
        total_score = required_score + preferred_score + ai_judgment_score
        
        reasoning = (
            f"필수 기술 점수: {required_score:.1f}/70 ({len(matched_required)}/{len(required_skills)} 매칭), "
            f"우대 기술 점수: {preferred_score:.1f}/20 ({len(matched_preferred)}/{len(preferred_skills)} 매칭), "
            f"AI 종합 판단 점수: {ai_judgment_score}/10. "
            f"최종 합계: {total_score:.1f}/100"
        )
        
        return {
            "match_score": round(total_score, 1),
            "matched_required_skills": matched_required,
            "matched_preferred_skills": matched_preferred,
            "missing_required_skills": missing_required,
            "reasoning": reasoning
        }
