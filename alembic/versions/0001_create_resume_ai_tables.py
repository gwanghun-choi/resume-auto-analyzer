"""create resume_ai tables

Revision ID: 0001_create_resume_ai_tables
Revises:
Create Date: 2026-06-09

resume_ai 스키마에 MVP 테이블 6개를 생성합니다.
모든 테이블/컬럼에 한국어 COMMENT 를 포함합니다. (DBeaver 에서 설명 확인 가능)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_create_resume_ai_tables"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "resume_ai"


def _created_updated():
    """모든 테이블 공통 created_at/updated_at 컬럼."""
    return [
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False,
                  server_default=sa.func.now(), comment="DB 레코드 생성 시각"),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True, comment="DB 레코드 수정 시각"),
    ]


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')

    # ----- departments -----
    op.create_table(
        "departments",
        sa.Column("id", sa.String(100), primary_key=True,
                  comment="부서 ID. Drive config JSON의 id 값을 그대로 사용합니다."),
        sa.Column("name", sa.String(255), nullable=False, comment="부서명"),
        sa.Column("parent_id", sa.String(100), nullable=True,
                  comment="상위 부서 ID. 부서 트리 구성에 사용합니다."),
        sa.Column("manager_id", sa.String(100), nullable=True, comment="부서 관리자 ID"),
        sa.Column("email", sa.String(255), nullable=True, comment="부서 또는 담당자 이메일"),
        sa.Column("sort", sa.Integer(), nullable=True, comment="부서 정렬 순서"),
        sa.Column("status", sa.Integer(), nullable=True,
                  comment="부서 상태값. 원본 부서 JSON의 status 값을 저장합니다."),
        sa.Column("register_date", sa.TIMESTAMP(), nullable=True, comment="원본 시스템의 부서 등록일"),
        sa.Column("update_date", sa.TIMESTAMP(), nullable=True, comment="원본 시스템의 부서 수정일"),
        sa.Column("synced_at", sa.TIMESTAMP(), nullable=True,
                  comment="Drive config 기준으로 DB에 마지막 동기화된 시각"),
        *_created_updated(),
        schema=SCHEMA,
        comment="부서 정보를 저장하는 테이블. Google Drive config/dept_config.json에서 동기화된 부서 트리 데이터입니다.",
    )
    op.create_index("ix_departments_parent_id", "departments", ["parent_id"], schema=SCHEMA)
    op.create_index("ix_departments_status", "departments", ["status"], schema=SCHEMA)
    op.create_index("ix_departments_name", "departments", ["name"], schema=SCHEMA)

    # ----- job_descriptions -----
    op.create_table(
        "job_descriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True,
                  comment="JD 내부 식별자"),
        sa.Column("dept_id", sa.String(100), nullable=False, comment="JD가 연결된 부서 ID"),
        sa.Column("title", sa.String(255), nullable=True, comment="JD 제목 또는 포지션명"),
        sa.Column("description", sa.Text(), nullable=True, comment="JD 본문 또는 업무 설명"),
        sa.Column("required_skills", postgresql.JSONB(), nullable=True, comment="필수 기술/요건 목록"),
        sa.Column("preferred_skills", postgresql.JSONB(), nullable=True, comment="우대 기술/요건 목록"),
        sa.Column("min_years", sa.Integer(), nullable=True, comment="최소 요구 경력 연수"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1", comment="JD 버전"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true",
                  comment="현재 사용 중인 JD 여부"),
        *_created_updated(),
        schema=SCHEMA,
        comment="부서별 채용 JD 정보를 저장하는 테이블입니다. 이력서 분석 시 부서별 평가 기준으로 사용됩니다.",
    )
    op.create_index("ix_job_descriptions_dept_id", "job_descriptions", ["dept_id"], schema=SCHEMA)
    op.create_index("ix_job_descriptions_is_active", "job_descriptions", ["is_active"], schema=SCHEMA)
    op.create_index("ix_job_descriptions_dept_id_is_active", "job_descriptions",
                    ["dept_id", "is_active"], schema=SCHEMA)

    # ----- dept_drive_folders -----
    op.create_table(
        "dept_drive_folders",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True,
                  comment="Drive 폴더 매핑 내부 식별자"),
        sa.Column("dept_id", sa.String(100), nullable=False, comment="부서 ID"),
        sa.Column("dept_name", sa.String(255), nullable=True, comment="동기화 시점의 부서명"),
        sa.Column("folder_name", sa.String(500), nullable=True,
                  comment="Google Drive에 생성된 부서 폴더명"),
        sa.Column("inbox_folder_id", sa.String(255), nullable=True,
                  comment="Google Drive inbox 하위 부서 폴더 ID"),
        sa.Column("completed_folder_id", sa.String(255), nullable=True,
                  comment="Google Drive completed 하위 부서 폴더 ID"),
        sa.Column("failed_folder_id", sa.String(255), nullable=True,
                  comment="Google Drive failed 하위 부서 폴더 ID"),
        sa.Column("synced_at", sa.TIMESTAMP(), nullable=True,
                  comment="Drive 폴더 매핑이 마지막으로 동기화된 시각"),
        *_created_updated(),
        sa.UniqueConstraint("dept_id", name="uq_dept_drive_folders_dept_id"),
        schema=SCHEMA,
        comment="부서별 Google Drive 폴더 ID 매핑 정보를 저장하는 테이블입니다. inbox, completed, failed 폴더 ID를 관리합니다.",
    )
    op.create_index("ix_dept_drive_folders_inbox_folder_id", "dept_drive_folders",
                    ["inbox_folder_id"], schema=SCHEMA)
    op.create_index("ix_dept_drive_folders_completed_folder_id", "dept_drive_folders",
                    ["completed_folder_id"], schema=SCHEMA)
    op.create_index("ix_dept_drive_folders_failed_folder_id", "dept_drive_folders",
                    ["failed_folder_id"], schema=SCHEMA)

    # ----- resume_upload_batches -----
    op.create_table(
        "resume_upload_batches",
        sa.Column("upload_id", sa.String(100), primary_key=True,
                  comment="업로드 회차 ID. 예: UPL20260609_111954"),
        sa.Column("dept_id", sa.String(100), nullable=False, comment="업로드 대상 부서 ID"),
        sa.Column("dept_name", sa.String(255), nullable=True, comment="업로드 시점의 부서명"),
        sa.Column("upload_folder_name", sa.String(500), nullable=False,
                  comment="Google Drive inbox 하위에 생성된 업로드 회차 폴더명"),
        sa.Column("source_upload_file_name", sa.String(500), nullable=True,
                  comment="사용자가 업로드한 원본 파일명. 여러 파일이면 multiple_files"),
        sa.Column("source_label", sa.String(255), nullable=True,
                  comment="원본 업로드 파일명 기반 표시용 라벨. 후보자명이 아닙니다."),
        sa.Column("upload_type", sa.String(50), nullable=True,
                  comment="업로드 유형. SINGLE_FILE, MULTIPLE_FILES, ZIP, MIXED_FILES 등"),
        sa.Column("drive_upload_folder_id", sa.String(255), nullable=True,
                  comment="Google Drive에 생성된 업로드 회차 폴더 ID"),
        sa.Column("drive_path_display", sa.Text(), nullable=True, comment="화면 표시용 Google Drive 경로"),
        sa.Column("status", sa.String(50), nullable=True, comment="업로드 회차 상태"),
        sa.Column("uploaded_count", sa.Integer(), server_default="0", comment="업로드 성공 파일 수"),
        sa.Column("skipped_count", sa.Integer(), server_default="0", comment="제외 또는 스킵된 파일 수"),
        sa.Column("completed_count", sa.Integer(), server_default="0", comment="분석 완료 파일 수"),
        sa.Column("failed_count", sa.Integer(), server_default="0", comment="분석 실패 파일 수"),
        sa.Column("pending_count", sa.Integer(), server_default="0", comment="분석 대기 파일 수"),
        sa.Column("inbox_upload_folder_cleanup", postgresql.JSONB(), nullable=True,
                  comment="분석 후 빈 inbox 업로드 폴더 정리 결과"),
        *_created_updated(),
        schema=SCHEMA,
        comment="이력서 업로드 회차 정보를 저장하는 테이블입니다. 사용자가 업로드 버튼을 한 번 누른 단위를 의미합니다.",
    )
    op.create_index("ix_resume_upload_batches_dept_id", "resume_upload_batches", ["dept_id"], schema=SCHEMA)
    op.create_index("ix_resume_upload_batches_status", "resume_upload_batches", ["status"], schema=SCHEMA)
    op.create_index("ix_resume_upload_batches_created_at", "resume_upload_batches", ["created_at"], schema=SCHEMA)
    op.create_index("ix_resume_upload_batches_dept_id_status", "resume_upload_batches",
                    ["dept_id", "status"], schema=SCHEMA)
    op.create_index("ix_resume_upload_batches_dept_id_created_at", "resume_upload_batches",
                    ["dept_id", "created_at"], schema=SCHEMA)

    # ----- resume_files -----
    op.create_table(
        "resume_files",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True,
                  comment="이력서 파일 내부 식별자"),
        sa.Column("upload_id", sa.String(100), nullable=False, comment="업로드 회차 ID"),
        sa.Column("dept_id", sa.String(100), nullable=False, comment="파일이 업로드된 부서 ID"),
        sa.Column("original_file_name", sa.String(500), nullable=True, comment="원본 파일명"),
        sa.Column("stored_file_name", sa.String(500), nullable=True, comment="Google Drive에 저장된 파일명"),
        sa.Column("drive_file_id", sa.String(255), nullable=True, comment="Google Drive 파일 ID"),
        sa.Column("file_size", sa.BigInteger(), nullable=True, comment="파일 크기 byte"),
        sa.Column("content_type", sa.String(255), nullable=True, comment="업로드 시 확인된 MIME 타입"),
        sa.Column("extension", sa.String(50), nullable=True, comment="파일 확장자"),
        sa.Column("file_status", sa.String(50), nullable=True, comment="파일 업로드 상태"),
        sa.Column("analysis_status", sa.String(50), nullable=True, comment="파일 분석 상태"),
        sa.Column("move_status", sa.String(50), nullable=True,
                  comment="Google Drive completed/failed 이동 상태"),
        sa.Column("moved_to", sa.String(50), nullable=True,
                  comment="분석 후 이동된 위치. completed 또는 failed"),
        sa.Column("moved_drive_file_id", sa.String(255), nullable=True,
                  comment="이동 후 Google Drive 파일 ID"),
        sa.Column("error_code", sa.String(100), nullable=True, comment="파일 처리 또는 분석 실패 코드"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="파일 처리 또는 분석 실패 메시지"),
        sa.Column("score", sa.Integer(), nullable=True, comment="AI 분석 점수 요약. 0~100"),
        sa.Column("recommendation", sa.String(100), nullable=True, comment="AI 추천 문구 요약"),
        sa.Column("analyzed_at", sa.TIMESTAMP(), nullable=True, comment="분석 완료 또는 실패 시각"),
        *_created_updated(),
        schema=SCHEMA,
        comment="이력서 파일 단위 정보를 저장하는 테이블입니다. 현재 MVP에서는 파일 1개를 지원자 1명으로 간주합니다.",
    )
    for col in ["upload_id", "dept_id", "drive_file_id", "file_status", "analysis_status",
                "move_status", "created_at", "analyzed_at"]:
        op.create_index(f"ix_resume_files_{col}", "resume_files", [col], schema=SCHEMA)
    op.create_index("ix_resume_files_dept_id_analysis_status", "resume_files",
                    ["dept_id", "analysis_status"], schema=SCHEMA)
    op.create_index("ix_resume_files_dept_id_created_at", "resume_files",
                    ["dept_id", "created_at"], schema=SCHEMA)

    # ----- resume_analysis_results -----
    op.create_table(
        "resume_analysis_results",
        sa.Column("analysis_id", sa.String(100), primary_key=True,
                  comment="분석 결과 ID. 예: ANL20260609_120102_001"),
        sa.Column("resume_file_id", sa.BigInteger(), nullable=True, comment="분석 대상 resume_files.id"),
        sa.Column("upload_id", sa.String(100), nullable=False, comment="업로드 회차 ID"),
        sa.Column("dept_id", sa.String(100), nullable=False, comment="분석 대상 부서 ID"),
        sa.Column("original_file_name", sa.String(500), nullable=True, comment="원본 파일명"),
        sa.Column("stored_file_name", sa.String(500), nullable=True, comment="Google Drive에 저장된 파일명"),
        sa.Column("drive_file_id", sa.String(255), nullable=True, comment="분석 대상 Google Drive 파일 ID"),
        sa.Column("completed_drive_file_id", sa.String(255), nullable=True,
                  comment="completed 이동 후 Google Drive 파일 ID"),
        sa.Column("source_drive_folder", sa.String(50), nullable=True,
                  comment="분석 전 파일이 위치한 Drive 영역. 보통 inbox"),
        sa.Column("moved_to", sa.String(50), nullable=True,
                  comment="분석 후 이동 위치. completed 또는 failed"),
        sa.Column("analysis_status", sa.String(50), nullable=True,
                  comment="분석 결과 상태. COMPLETED 또는 FAILED"),
        sa.Column("move_status", sa.String(50), nullable=True, comment="Google Drive 파일 이동 상태"),
        sa.Column("score", sa.Integer(), nullable=True, comment="AI 분석 점수. 0~100"),
        sa.Column("recommendation", sa.String(100), nullable=True,
                  comment="AI 추천 문구. 우선 검토 추천, 추가 검토 필요, 낮은 적합도"),
        sa.Column("summary", sa.Text(), nullable=True, comment="이력서 분석 요약"),
        sa.Column("strengths", postgresql.JSONB(), nullable=True, comment="강점 목록"),
        sa.Column("weaknesses", postgresql.JSONB(), nullable=True, comment="보완점 목록"),
        sa.Column("matched_skills", postgresql.JSONB(), nullable=True, comment="JD와 매칭된 기술 목록"),
        sa.Column("missing_skills", postgresql.JSONB(), nullable=True, comment="JD 대비 부족한 기술 목록"),
        sa.Column("reasoning", sa.Text(), nullable=True, comment="AI 분석 근거"),
        sa.Column("error_code", sa.String(100), nullable=True, comment="분석 실패 코드"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="분석 실패 메시지"),
        sa.Column("raw_response", postgresql.JSONB(), nullable=True,
                  comment="LLM 원본 응답 또는 파싱 전 응답 일부"),
        sa.Column("analyzed_at", sa.TIMESTAMP(), nullable=True, comment="분석 완료 또는 실패 시각"),
        *_created_updated(),
        schema=SCHEMA,
        comment="이력서 AI 분석 결과 상세를 저장하는 테이블입니다. 점수, 추천, 요약, 강점/보완점 등을 저장합니다.",
    )
    for col in ["resume_file_id", "upload_id", "dept_id", "analysis_status",
                "recommendation", "score", "analyzed_at"]:
        op.create_index(f"ix_resume_analysis_results_{col}", "resume_analysis_results", [col], schema=SCHEMA)
    op.create_index("ix_resume_analysis_results_dept_id_analyzed_at", "resume_analysis_results",
                    ["dept_id", "analyzed_at"], schema=SCHEMA)
    op.create_index("ix_resume_analysis_results_dept_id_recommendation", "resume_analysis_results",
                    ["dept_id", "recommendation"], schema=SCHEMA)


def downgrade() -> None:
    # 테이블만 제거합니다. (schema 자체는 삭제하지 않습니다.)
    op.drop_table("resume_analysis_results", schema=SCHEMA)
    op.drop_table("resume_files", schema=SCHEMA)
    op.drop_table("resume_upload_batches", schema=SCHEMA)
    op.drop_table("dept_drive_folders", schema=SCHEMA)
    op.drop_table("job_descriptions", schema=SCHEMA)
    op.drop_table("departments", schema=SCHEMA)
