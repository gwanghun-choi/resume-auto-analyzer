from sqlalchemy import Column, String, Integer, BigInteger, Text, TIMESTAMP, Index
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base, TimestampMixin

# resume_analysis_results: AI 분석 결과 상세. (기존 analysis_results.json 을 대체 예정)
# 분석 실패 시 가짜 점수/결과를 만들지 않습니다. 추천 문구만 저장합니다.


class ResumeAnalysisResult(Base, TimestampMixin):
    __tablename__ = "resume_analysis_results"
    __table_args__ = (
        Index("ix_resume_analysis_results_resume_file_id", "resume_file_id"),
        Index("ix_analysis_results_posting_id", "posting_id"),
        Index("ix_analysis_results_jd_id", "jd_id"),
        Index("ix_resume_analysis_results_upload_id", "upload_id"),
        Index("ix_resume_analysis_results_dept_id", "dept_id"),
        Index("ix_resume_analysis_results_analysis_status", "analysis_status"),
        Index("ix_resume_analysis_results_recommendation", "recommendation"),
        Index("ix_resume_analysis_results_score", "score"),
        Index("ix_resume_analysis_results_analyzed_at", "analyzed_at"),
        Index("ix_resume_analysis_results_dept_id_analyzed_at", "dept_id", "analyzed_at"),
        Index("ix_resume_analysis_results_dept_id_recommendation", "dept_id", "recommendation"),
        {"comment": "이력서 AI 분석 결과 상세를 저장하는 테이블입니다. 점수, 추천, 요약, 강점/보완점 등을 저장합니다."},
    )

    analysis_id = Column(String(100), primary_key=True,
                         comment="분석 결과 ID. 예: ANL20260609_120102_001")
    resume_file_id = Column(BigInteger, nullable=True, comment="분석 대상 resume_files.id")
    upload_id = Column(String(100), nullable=False, comment="업로드 회차 ID")
    dept_id = Column(String(100), nullable=False, comment="분석 대상 부서 ID (권한/호환용, 유지)")
    # 공고/JD 중심 전환: 분석 기준 공고/JD + 분석 당시 JD 스냅샷
    posting_id = Column(BigInteger, nullable=True, comment="분석 기준 공고 id (job_postings.id)")
    jd_id = Column(BigInteger, nullable=True, comment="분석 기준 JD id (job_posting_jds.id)")
    jd_snapshot = Column(JSONB, nullable=True, comment="분석 당시 JD 스냅샷(title/required/preferred/jd_content)")
    original_file_name = Column(String(500), nullable=True, comment="원본 파일명")
    stored_file_name = Column(String(500), nullable=True, comment="Google Drive에 저장된 파일명")
    drive_file_id = Column(String(255), nullable=True, comment="분석 대상 Google Drive 파일 ID")
    completed_drive_file_id = Column(String(255), nullable=True,
                                     comment="completed 이동 후 Google Drive 파일 ID")
    source_drive_folder = Column(String(50), nullable=True,
                                 comment="분석 전 파일이 위치한 Drive 영역. 보통 inbox")
    moved_to = Column(String(50), nullable=True,
                      comment="분석 후 이동 위치. completed 또는 failed")
    analysis_status = Column(String(50), nullable=True,
                             comment="분석 결과 상태. COMPLETED 또는 FAILED")
    move_status = Column(String(50), nullable=True, comment="Google Drive 파일 이동 상태")
    score = Column(Integer, nullable=True, comment="AI 분석 점수. 0~100")
    recommendation = Column(String(100), nullable=True,
                            comment="AI 추천 문구. 우선 검토 추천, 추가 검토 필요, 낮은 적합도")
    summary = Column(Text, nullable=True, comment="이력서 분석 요약")
    strengths = Column(JSONB, nullable=True, comment="강점 목록")
    weaknesses = Column(JSONB, nullable=True, comment="보완점 목록")
    matched_skills = Column(JSONB, nullable=True, comment="JD와 매칭된 기술 목록")
    missing_skills = Column(JSONB, nullable=True, comment="JD 대비 부족한 기술 목록")
    reasoning = Column(Text, nullable=True, comment="AI 분석 근거")
    error_code = Column(String(100), nullable=True, comment="분석 실패 코드")
    error_message = Column(Text, nullable=True, comment="분석 실패 메시지")
    raw_response = Column(JSONB, nullable=True, comment="LLM 원본 응답 또는 파싱 전 응답 일부")
    analyzed_at = Column(TIMESTAMP, nullable=True, comment="분석 완료 또는 실패 시각")
