# resume_ai 스키마의 ORM 모델 모음.
# app/db/base.py 가 이 패키지를 import 해서 Alembic 이 모든 테이블 metadata 를 인식합니다.

from app.db.models.department import Department
from app.db.models.job_description import JobDescription
from app.db.models.dept_drive_folder import DeptDriveFolder
from app.db.models.resume_upload_batch import ResumeUploadBatch
from app.db.models.resume_file import ResumeFile
from app.db.models.resume_analysis_result import ResumeAnalysisResult
from app.db.models.user import User
from app.db.models.job_posting import JobPosting
from app.db.models.job_posting_jd import JobPostingJD

__all__ = [
    "Department",
    "JobDescription",
    "DeptDriveFolder",
    "ResumeUploadBatch",
    "ResumeFile",
    "ResumeAnalysisResult",
    "User",
    "JobPosting",
    "JobPostingJD",
]
