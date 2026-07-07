import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
from app.api import resume_router, dept_router, jd_router, upload_router, analyze_router, drive_router, departments_router, resumes_router, db_router, jds_router, auth_router, admin_users_router, job_postings_router, jobs_router
from app.core.config import settings
from app.core.security import SESSION_USER_KEY


os.environ.setdefault("SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt")
os.environ.setdefault("REQUESTS_CA_BUNDLE", "/etc/ssl/certs/ca-certificates.crt")
os.environ.setdefault("HTTPLIB2_CA_CERTS", "/etc/ssl/certs/ca-certificates.crt")

# .env 파일 로드 (Spring의 application.properties 또는 .yml 로드와 비슷합니다)
load_dotenv()

# FastAPI 인스턴스 생성 (Java/Spring Boot의 @SpringBootApplication과 비슷합니다)
app = FastAPI(
    title="Resume AI Analyzer (OpenAI GPT)",
    description="이력서 AI 분석 및 점수 산정 데모 (LLM: OpenAI)",
    version="0.1.0"
)

# 세션 미들웨어 (로그인 상태를 서명된 쿠키 세션으로 유지). JWT 가 아니라 세션 방식입니다.
# secret_key 는 설정에서 읽습니다. (운영은 .env 의 SESSION_SECRET_KEY 사용)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET_KEY,
    same_site="lax",
    https_only=False,
)

# 정적 파일 설정 (CSS, JS) - Spring의 resources/static과 비슷합니다.
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 템플릿 설정 (HTML)
templates = Jinja2Templates(directory="app/templates")

# 라우터 등록 (Spring 의 Controller 들을 등록하는 것과 비슷합니다)
#
# 신규 개발 기준: **공고(job posting) 중심 플로우만** 사용합니다. (docs/WORKFLOW.md 참고)
#   [KEEP  · 공고 중심] job_postings_router, resumes_router(analyze-posting/selected/all), jobs_router, auth_router, admin_users_router
#   [INFRA · 관리]     drive_router, departments_router, db_router
#   [LEGACY · 부서 중심] dept_router, upload_router, resume_router, analyze_router, jd_router, jds_router
#                       — 하위호환 위해 include 유지하나 신규 개발 대상 아님(파일별 LEGACY 주석 참고). 삭제는 후속 결정(docs/TODO).
app.include_router(dept_router.router)      # LEGACY GET /api/depts : 부서 목록(더미)
app.include_router(jd_router.router)        # GET/POST /api/jd      : 팀별 JD 조회/저장
app.include_router(upload_router.router)    # POST /api/uploads     : 팀 기준 파일 업로드
app.include_router(analyze_router.router)   # POST /api/analyze     : 팀 JD 기준 분석
app.include_router(resume_router.router)    # POST /api/resume      : (기존) 단일 파일 분석 - 호환용 유지
app.include_router(drive_router.router)     # GET /api/drive/test   : Google Drive 연결 확인 + 기본 폴더 생성
app.include_router(departments_router.router) # GET /api/departments/tree : 부서 트리(캐시 기준) / 캐시 새로고침
app.include_router(resumes_router.router)   # POST /api/resumes/upload-to-drive : 이력서 파일 Drive inbox 업로드
app.include_router(db_router.router)        # GET /api/db/health    : PostgreSQL 연결 health check
app.include_router(jds_router.router)       # /api/jds              : JD CRUD (DB job_descriptions)
app.include_router(auth_router.router)      # /api/auth             : 로그인/로그아웃/me (세션)
app.include_router(admin_users_router.router)  # /api/admin/users, /api/admin/departments/search (ADMIN 전용)
app.include_router(job_postings_router.router)  # /api/job-postings : 공고/JD 관리 (공고 중심 전환)
app.include_router(jobs_router.router)       # /api/jobs/extract-from-url : 공고 URL 기반 자동 채우기 (LLM)


def _is_logged_in(request: Request) -> bool:
    """세션에 user_id 가 있으면 로그인 상태로 봅니다. (페이지 접근 제어용 간단 판단)"""
    return bool(request.session.get(SESSION_USER_KEY))


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """메인 인덱스 페이지. 로그인하지 않았으면 /login 으로 리다이렉트합니다."""
    if not _is_logged_in(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={}
    )


@app.get("/login", response_class=HTMLResponse)
async def read_login(request: Request):
    """로그인 페이지. 이미 로그인 상태면 / 로 리다이렉트합니다."""
    if _is_logged_in(request):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={}
    )

# 서버 시작 시 실행되는 이벤트 (Spring의 @PostConstruct와 유사한 개념)
@app.on_event("startup")
async def startup_event():
    # LLM provider(OpenAI) 설정을 로그로 확인합니다. (키 값은 출력하지 않음)
    from app.services.openai_llm_service import log_llm_config, api_key_present
    log_llm_config()
    if not api_key_present():
        print("경고: OPENAI_API_KEY가 설정되지 않았습니다. JD 추천/이력서 분석 기능은 동작하지 않습니다. (.env 확인)")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
