import json
from pathlib import Path
from datetime import datetime
from typing import List

from app.schemas.jd_schema import JD
from app.schemas.analysis_response import FileAnalysisResult
from app.services.upload_service import UploadService
from app.services.resume_parser_service import ResumeParserService
from app.services.ai_agent_service import AiAgentService
from app.services.matching_service import MatchingService

# LEGACY: 부서 기준 + 로컬 파일시스템(data/storage) 분석 서비스. 공고 중심 전환으로 신규 개발 대상이 아닙니다.
#         신규/비동기(Celery) 분석은 공고 기준 resume_analysis_service.analyze_posting 만 사용하세요.
#         (analyze_router 에서만 사용. 동작 변경 금지, 후속 제거 검토 — docs/TODO.)
#
# BatchService 는 "업로드된 파일 목록을 순회하면서 분석" 하는 서비스입니다.
#
# 지금은 요청이 들어오면 바로 한 번에 돌리지만,
# 나중에 스케줄러/배치(예: 야간 일괄 처리)로 바꿀 수 있도록 따로 분리했습니다.
#
# 핵심 정책:
#  - 파일 하나가 실패해도 전체를 실패시키지 않습니다. (해당 파일에 error 만 기록)
#  - 추출된 텍스트가 비어 있으면 그 파일은 분석 실패로 처리합니다.
#  - 추천 문구(recommendation)는 점수 구간으로 결정합니다. (탈락/불합격 표현 금지)

RESULTS_DIR = Path("data/storage/results")
FAILED_DIR = Path("data/storage/failed")


def recommendation_for_score(score: float) -> str:
    """
    점수 구간별 추천 문구.
    - 80점 이상: 우선 검토 추천
    - 60점 이상 80점 미만: 추가 검토 필요
    - 60점 미만: 낮은 적합도
    (자동 탈락/불합격 같은 표현은 사용하지 않습니다.)
    """
    if score >= 80:
        return "우선 검토 추천"
    if score >= 60:
        return "추가 검토 필요"
    return "낮은 적합도"


class BatchService:
    def __init__(self):
        # 기존 단일 분석에서 쓰던 서비스들을 그대로 재사용합니다.
        self.upload_service = UploadService()
        self.parser = ResumeParserService()
        self.ai_service = AiAgentService()
        self.matcher = MatchingService()

    def analyze_upload(self, jd: JD, dept_id: str, upload_id: str) -> List[FileAnalysisResult]:
        """
        업로드 묶음(upload_id) 안의 파일들을 JD 기준으로 분석합니다.
        결과 리스트를 반환하고, 동시에 JSON 파일로도 저장합니다.
        """
        file_paths = self.upload_service.list_files(dept_id, upload_id)
        results: List[FileAnalysisResult] = []

        for path in file_paths:
            results.append(self._analyze_one(jd, path))

        # 결과 JSON 저장 (data/storage/results/{dept_id}/YYYY/MM/DD/{upload_id}/result.json)
        self._save_results(dept_id, upload_id, results)
        return results

    def _analyze_one(self, jd: JD, path: Path) -> FileAnalysisResult:
        """파일 1개 분석. 실패하면 error 필드만 채운 결과를 돌려줍니다."""
        file_name = path.name
        try:
            content = path.read_bytes()
            # parse_resume 는 텍스트가 비어 있으면 예외를 던집니다 -> 분석 실패로 처리됩니다.
            resume_text = self.parser.parse_resume(content, file_name)

            ai_result = self.ai_service.analyze(
                resume_text=resume_text,
                position=jd.position_title,
                required_skills=jd.required_skills,
                preferred_skills=jd.preferred_skills,
            )

            match_result = self.matcher.calculate_match(
                extracted_skills=ai_result.get("extracted_skills", []),
                required_skills=jd.required_skills,
                preferred_skills=jd.preferred_skills,
                ai_judgment_score=ai_result.get("ai_judgment_score", 0),
            )

            score = match_result["match_score"]
            return FileAnalysisResult(
                file_name=file_name,
                candidate_summary=ai_result.get("candidate_summary", ""),
                extracted_skills=ai_result.get("extracted_skills", []),
                career_summary=ai_result.get("career_summary", ""),
                match_score=score,
                matched_required_skills=match_result["matched_required_skills"],
                matched_preferred_skills=match_result["matched_preferred_skills"],
                missing_required_skills=match_result["missing_required_skills"],
                strengths=ai_result.get("strengths", []),
                weaknesses=ai_result.get("weaknesses", []),
                recommendation=recommendation_for_score(score),
                reasoning=match_result["reasoning"],
            )
        except Exception as e:
            # 한 파일의 실패가 전체를 막지 않도록 error 만 채워서 반환합니다.
            detail = getattr(e, "detail", None) or str(e)
            self._save_failed(jd.dept_id, file_name, detail)
            return FileAnalysisResult(file_name=file_name, error=detail)

    def _result_dir(self, dept_id: str, upload_id: str, base: Path) -> Path:
        now = datetime.now()
        return base / dept_id / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d") / upload_id

    def _save_results(self, dept_id: str, upload_id: str, results: List[FileAnalysisResult]) -> None:
        out_dir = self._result_dir(dept_id, upload_id, RESULTS_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = [r.model_dump() for r in results]
        (out_dir / "result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_failed(self, dept_id: str, file_name: str, error: str) -> None:
        """실패한 파일 정보를 failed 폴더에 기록해 둡니다. (추후 추적용)"""
        now = datetime.now()
        out_dir = FAILED_DIR / dept_id / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
        out_dir.mkdir(parents=True, exist_ok=True)
        record = {"file_name": file_name, "error": error, "time": now.isoformat(timespec="seconds")}
        # 파일명 충돌을 피하려고 시각을 붙여 저장합니다.
        stamp = now.strftime("%H%M%S%f")
        (out_dir / f"{stamp}_{file_name}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
