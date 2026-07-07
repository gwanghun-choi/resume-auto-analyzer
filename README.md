# Resume AI Analyzer (OpenAI GPT)

FastAPI 기반 **이력서 분석/매칭** 시스템입니다.
**채용 공고(job_posting)** 와 그에 연결된 **JD** 를 기준으로 이력서를 분석하고, 점수·추천·매칭 결과를 제공합니다.
**부서/팀** 은 권한·조직·필터 기준으로 유지됩니다.

> 향후 개발 예정 기능은 [`docs/TODO.md`](docs/TODO.md), 사용자 업무 흐름은 [`docs/WORKFLOW.md`](docs/WORKFLOW.md),
> 구조 전환 작업 기록은 [`docs/work-log/`](docs/work-log/) 를 참고하세요.

---

## 0. 구조: "공고/JD 중심" (부서/팀은 권한·필터 기준으로 유지, 2026-06)

채용 단위는 **공고(job_posting)** 이며, 공고에 연결된 **JD** 를 기준으로 이력서를 등록·분석·조회합니다.

- **공고(job_postings)** = 실제 채용 단위. 외부 플랫폼(사람인/잡코리아/원티드/기타) 공고와 1:1 대응(현재). 부서·플랫폼·상태·**Drive 공고 폴더** 보유.
- **JD(job_posting_jds)** = 공고에 연결된 매칭 기준이자 **현재 JD 기준 테이블**. **현재 1공고 = 1 active JD**(서비스 강제, 향후 N 확장 대비 테이블 분리).
- **`job_descriptions`(부서별 JD)** = **legacy/미사용** 테이블입니다. 공고/JD 전환으로 핵심 업무 기준에서 빠졌고, `관리자 > Drive 설정/동기화` 화면의 `job_descriptions` 카드/현황 팝업도 제거되었습니다. (부서 기준 분석 fallback 등 일부 legacy 경로에만 잔존)
- **부서/팀(departments)** = 삭제하지 않고 **권한·조직·필터 기준으로 유지**. Drive `dept_config.json`/부서 동기화도 유지.
- **이력서/분석 결과** = `posting_id`/`jd_id` 로 공고/JD에 종속. 업로드 시 `dept_id = posting.department_id` 복사. `posting_id` 없는 기존 데이터는 "미매핑(공고명 '-')" 으로 안전 표시.

### 업무 흐름 (공고 기준)
외부 플랫폼 공고 등록 → **공고/JD 관리**에서 공고 등록 → 공고 상세에서 **JD 등록**(= **이 시점에 Drive 공고 폴더 자동 생성**) → **이력서 등록**(공고 선택 후 업로드) → **분석 작업 관리**(공고 선택 → 대기 파일 분석) → **이력서 현황**(공고 기준 조회).

### Drive 공고 폴더 (생성 시점 = JD 등록 완료)
```
resume-demo-root / inbox     / {JP000001_공고명}
resume-demo-root / completed / {JP000001_공고명}
resume-demo-root / failed    / {JP000001_공고명}
```
- 공고 등록 시점에는 폴더를 만들지 않습니다(JD 미등록 = 업로드/분석 대상 아님). **JD 등록/저장 성공 시점**에 폴더가 없으면 생성하고 folder id 를 `job_postings.drive_inbox/completed/failed_folder_id` 에 저장합니다(이미 있으면 재생성하지 않음 — 멱등). JD 저장 + Drive 생성은 한 트랜잭션이라 **Drive 생성 실패 시 JD 저장도 롤백**됩니다.
- 부서 폴더를 중간 경로로 두지 않고 공고명 기준으로 바로 생성합니다. (이전 `postings/{부서}/...` 구조는 **legacy** — 기존 폴더는 삭제하지 않음)
- 기존 부서 폴더 동기화(`inbox/completed/failed` 아래 **부서** 폴더, `dept_drive_folders`)는 그대로 유지됩니다.

### 주요 API
- 공고/JD: `GET/POST /api/job-postings`, `GET /api/job-postings/search`, `GET /api/job-postings/dept-search`(권한범위 부서검색), `GET/PUT /{id}`, `PATCH /{id}/status`, `GET/POST/PUT /{id}/jd`, `POST /{id}/jd/recommend`(공고명·부서명 기반 **추천 JD 초안**, OpenAI, DB 저장 안 함).
  - 공고 상세/수정 팝업은 **공고 기본 정보 + JD 상세를 한 화면에 통합 입력**(JD 카드 처음부터 표시), **저장 버튼 하나**(신규=`공고 등록` / 수정=`공고 수정`)로 공고+JD를 함께 저장(공고→`job_postings`, JD→**`job_posting_jds`**, 서로 다른 테이블 유지). JD 카드 우상단 **[추천 JD]** 버튼(ADMIN 전체 / MANAGER 본인 부서+하위 / VIEWER 숨김). JD 입력 라벨은 **자격 요건 / 우대 사항 / 주요 업무**(내부 필드 `required_skills`/`preferred_skills`/`jd_content` 및 점수 산식은 불변 — textarea 줄바꿈/콤마 → JSONB 배열). `job_descriptions` 는 legacy 테이블로 공고 JD 와 무관.
  - **부서/팀은 선택사항**(미지정 가능). `job_postings.department_id` 는 nullable([`docs/sql/2026-06-12-job-postings-dept-nullable.sql`](docs/sql/2026-06-12-job-postings-dept-nullable.sql) 적용). 부서/팀은 사용자가 직접 검색·선택(자동 추출/선택 안 함).
- 공고 URL 자동 채우기: `POST /api/jobs/extract-from-url` — 플랫폼 공고 URL 옆 **[공고 내용 가져오기]** 버튼. **디딤(주) 공고로 확인된 경우에만** 페이지 본문을 수집해 OpenAI 로 공고명/주요업무/자격요건/우대사항을 구조화해 JD textarea까지 채움(섹션 라벨 동의어 인식, 플랫폼은 URL 도메인 기준).
  - **JD 수집 fallback**(`collector_method`): ① 정적 HTML 본문(`STATIC_HTML`) → ② **사람인 상세 iframe**(`/zf_user/jobs/relay/view-detail?rec_idx=`)을 정적 fetch(`SARAMIN_DETAIL`) → ③ 동일 출처 iframe 정적 fetch(`IFRAME`). 사람인은 JD 본문이 JS 로드 iframe에 있어 메인 HTML에 없지만, 상세 URL을 **정적으로** 가져와 채움(**Playwright 미사용** — 가볍게 해결). 본문에 섹션이 있는데 LLM이 비우면 성공이 아닌 **경고**(`warning`+`debug_reason`)로 처리(조용한 성공 금지).
  - **공고명/JD명(`job_title`)은 공고 상단 제목 우선**: `og:title`/`<title>` 에서 정적 추출 후 사이트명·마감 D-day·회사명 대괄호 suffix 제거(예: `[디딤(주)] IDC 인프라 운영 엔지니어 채용(D-28) - 사람인` → `IDC 인프라 운영 엔지니어 채용`). **"모집분야"(예: IDC 인프라 엔지니어)는 공고명으로 우선 사용하지 않음** — 상단 제목을 못 찾을 때만 LLM 추출값 → 모집분야 순으로 fallback. 응답에 `posting_title`(상단 제목)/`recruit_field`(모집분야) 참고 필드 분리.
  - **이미 입력값이 있으면 confirm 후 덮어쓰기**(취소 시 유지), **부서/팀·상태는 변경 안 함**, **저장은 사용자가 직접**. 권한 ADMIN/MANAGER. SSRF 방어(사설/loopback/link-local IP·비 http(s)·리다이렉트 차단, iframe/상세 fetch도 동일 출처+재검증), 새 라이브러리 미추가(stdlib + 기존 OpenAI 서비스). **OpenAI key 등 민감정보는 응답/로그에 출력하지 않음.** (순수 JS 렌더링 전용 공고는 정적 수집 한계 — Playwright fallback 은 TODO)
- 이력서: `POST /api/resumes/upload-to-drive`(`posting_id`), `GET /api/resumes/status`(`posting_id`/`posting_keyword`). 이력서 등록 화면에서 공고 [업로드] 클릭 시 해당 공고의 **기존 미처리(분석 대기) 이력서 요약**(건수+파일명 일부, `posting-pending` 재사용)을 표시. 이력서 현황 부서 트리는 **상위 부서도 이름 클릭으로 선택**(화살표=펼치기/접기), 트리 내부 스크롤로 페이지가 밀리지 않음.
- 분석: `GET /api/resumes/posting-pending-counts`, `GET /api/resumes/posting-pending/{id}`, `POST /api/resumes/analyze-posting`(선택 공고), `POST /api/resumes/analyze-selected`(선택 항목), `POST /api/resumes/analyze-all`(**ADMIN 전용**).

### 목록 페이징
- **백엔드 페이징**, 카드 상단 `총 N건` + 하단 `[이전] p / N 페이지 [다음]`.
  - 페이지당 표시 select(20/30/50, 기본 20): **공고/JD 관리 · 이력서 등록 · 이력서 현황**.
  - **분석 작업 관리 > 공고/JD 목록**은 카드형 리스트라 size select 없이 **한 페이지 5개 고정**(이전/다음만). 분석 대기 파일 목록은 size select(20/30/50).
  - 검색/오늘/초기화/size 변경 시 1페이지부터 재조회.
- `GET /api/job-postings` 응답: `{items, total, page, size}` (total 은 권한 필터 적용). `GET /api/resumes/posting-pending/{id}?page&size`, `GET /api/resumes/status?...&page&size` 동일 구조. `department_id` 는 해당 부서+하위(subtree, 권한 밖 403).

### 화면 레이아웃
- 검색 필터 바(공고/JD 관리·이력서 등록·이력서 현황·분석)는 `[오늘] [날짜~날짜] [필터…] [공고명/파일명 검색] [검색] [초기화]`를 한 줄로 정렬(검색/초기화는 `toolbar-actions` 로 항상 같은 줄, 좁으면 그룹 단위 wrap). 이력서 현황 Excel 다운로드는 화면 우측 상단.
- 이력서 현황 부서 트리 카드는 뷰포트 높이로 캡 + 내부 스크롤(`overflow:hidden` + `max-height`)이라 트리를 펼쳐도 전체 페이지가 밀리지 않습니다.
- **분석 작업 관리는 3컬럼**: `[부서/팀(검색조건)] [공고/JD(320px·페이징)] [분석 대기 파일(페이징)+분석 실행]`. 부서/팀 트리는 이력서 현황과 동일 컴포넌트 재사용 — 부서 선택 시 해당 부서+하위 공고가 조회됩니다(`analysis-split`).

### 권한
ADMIN 전체 / MANAGER 본인 부서+하위 / VIEWER 본인 부서+하위 **조회만**(등록/수정/업로드/분석 불가). 전체 분석은 **ADMIN 전용**. 모든 권한은 프론트 숨김과 별개로 **백엔드에서 403 재검증**.

> DB 변경 SQL: [`docs/sql/2026-06-12-posting-jd.sql`](docs/sql/2026-06-12-posting-jd.sql) (resume_ai 전용, 적용 완료). 단계별 작업 기록: [`docs/work-log/`](docs/work-log/) 의 `2026-06-posting-jd-ui-step-01~05`. MatchingService 점수 산식/추천 기준은 **불변**.

---

## 공식 주력 플로우 = 공고 중심 / 레거시 = 부서 중심 (2026-07)

현재 **공식 주력 플로우는 공고(job posting) 중심**입니다. 과거 부서(department) 중심 이력서/JD 경로는 **레거시(하위호환용)** 이며 **신규 개발 대상이 아닙니다**. 레거시 경로는 이번 정리에서 삭제하지 않고 코드에 `LEGACY` 주석으로 표시했습니다(동작 불변).

**신규 개발은 아래 공고 중심 구성만 사용하세요.**

| 용도 | 사용(KEEP) | 사용 금지(LEGACY) |
| --- | --- | --- |
| 공고 등록 | `job_postings`, `job_postings_router`, `job_posting_service` | — |
| 공고별 JD | `job_posting_jds`, `POST/PUT /api/job-postings/{id}/jd` | `job_descriptions`, `jd_router`(/api/jd), `jds_router`(/api/jds), `jd_service`, `jd_db_service` |
| 이력서 업로드 | `resumes_router` + `resume_drive_upload_service`(공고 기준 Drive) | `upload_router`(/api/uploads), `upload_service`(로컬 FS) |
| 이력서 분석 | `resumes_router`(analyze-posting/selected/all) + `resume_analysis_service.analyze_posting` | `analyze_router`(/api/analyze), `resume_router`(/api/resume), `batch_service`, `resume_analysis_service.analyze_pending` |
| 이력서 현황/Excel | `resume_status_db_service`, `resume_status_excel_service` | — |
| 공고 URL 추출 | `jobs_router` + `job_extract_service` | — |
| 사람인 신규 공고 수집 | `saramin_job_collect_service` + `job_posting_discovery_service`(→ `job_postings`/`job_posting_jds`) | — |
| 부서 조회(권한/필터) | `department_access_service`, `department_db_service` | `dept_router`(/api/depts), `dept_service` |

- **INFRA/ADMIN(유지)**: `drive_router`, `departments_router`, `db_router` 및 Drive/부서 동기화 서비스 — 관리성 API 로 계속 사용.
- **사람인 신규 공고 수집 배치**는 공고 중심 흐름에 연결됩니다: 신규 공고는 `job_postings`, JD 는 `job_posting_jds`, 상세 분석은 `job_extract_service` 재사용, Drive 폴더는 `job_posting_service`/`job_posting_drive_service` 경로. (legacy `job_descriptions`/`jd_router`/`upload_service`/`batch_service` 미사용)
- **향후 Celery/비동기 분석**도 공고 중심(`analyze_posting` / `job_extract_service` / `job_posting_service`)만 큐 대상으로 합니다. 레거시 `analyze_pending`/`batch_service` 는 큐에 태우지 않습니다.

> 레거시 경로 분류 근거와 후속 제거 대상은 [`docs/work-log/2026-07-07-job-posting-flow-consolidation.md`](docs/work-log/2026-07-07-job-posting-flow-consolidation.md) 및 [`docs/TODO.md`](docs/TODO.md) 참고.

---

## 1. 프로젝트 개요

- **목적**: 부서/팀 JD 기준으로 이력서를 자동 분석해 채용 검토를 돕는 MVP.
- **주요 기능 요약**
  - FastAPI 기반 웹/API 서버 (단일 페이지 관리 화면 + REST API)
  - Google Drive 연동 (OAuth, `dept_config.json` 로드/저장, 부서 폴더 동기화, 이력서 업로드/이동)
  - OpenAI 기반 **JD 추천** 및 **이력서 분석**
  - PostgreSQL(`resume_ai` 스키마) 저장
  - Docker / Docker Compose 실행, NCP 서버 배포 가능
  - `.env` 기반 환경변수 관리, Google OAuth `credentials.json` / `token.json` 파일 인증
  - 회사망(Fortinet SSL inspection) 대응을 위한 Docker Root CA 설정

---

## 2. 현재 구현된 기능 (실제 코드 기준)

> 아래는 **현재 코드에 실제로 구현된 기능**만 적습니다. 미구현/예정 기능은 [`docs/TODO.md`](docs/TODO.md) 참고.

- **부서/팀 트리**: Google Drive `config/dept_config.json` 을 원천으로, DB `resume_ai.departments` 기준 조회. 트리 검색/접힘·펼침/선택 하이라이트.
- **Google Drive 연동**
  - OAuth 인증(`token.json` 로드/refresh, 최초 인증 플로우)
  - `dept_config.json` 불러오기/검증/업로드 정규화/저장
  - 부서 폴더 동기화(`inbox`/`completed`/`failed` 하위 부서 폴더 생성·재사용, `resume_ai.dept_drive_folders` 저장)
- **JD 관리**: 부서별 JD 조회/저장(DB `job_descriptions`), **추천JD**(OpenAI 로 설명/필수·우대 기술 초안 생성, 입력란 자동 채움 — DB 저장은 사용자가 직접).
- **이력서 업로드**: 선택 부서의 Drive `inbox/{회차}` 폴더에 업로드(ZIP 해제 포함), `resume_ai.resume_upload_batches` / `resume_files` 기록.
- **이력서 분석 실행**(요청 시 즉시 실행): pending 파일을 Drive 에서 내려받아 텍스트 추출 → OpenAI 분석 → 점수/추천/요약/강점·약점/매칭 → DB 저장 → `completed`/`failed` 이동. (파일 단위 성공/실패)
- **이력서 현황 조회**: 목록(부서/분석상태/추천/파일명/날짜 필터, 페이징 20건), 상세 모달, **Excel 다운로드**.
- **헬스/점검 API**: `/api/db/health`, `/api/db/counts`, `/api/drive/test`.

### 주요 API (요약)

| Method | Path | 설명 |
| --- | --- | --- |
| GET | `/` | 관리 화면(HTML) |
| GET | `/docs` | Swagger UI |
| GET | `/api/departments/tree` | 부서 트리(DB 기준) |
| GET/POST | `/api/jd/{dept_id}` | 부서 JD 조회/저장 |
| POST | `/api/jd/recommend` | 추천JD(OpenAI) |
| GET/POST/PUT/DELETE | `/api/jds` , `/api/jds/{id}` | JD CRUD(DB) |
| GET | `/api/drive/test` | Google Drive 연결 확인 + 기본 폴더 생성 |
| GET/PUT | `/api/drive/dept-config` | `dept_config.json` 조회/저장 |
| POST | `/api/drive/sync-dept-folders` | 부서 폴더 동기화 |
| POST | `/api/resumes/upload-to-drive` | 이력서 Drive 업로드 |
| GET | `/api/resumes/pending-uploads` | 분석 대기 파일 조회 |
| POST | `/api/resumes/analyze-pending` | 이력서 분석 실행 |
| GET | `/api/resumes/status` , `/status/{id}` | 이력서 현황 목록/상세 |
| GET | `/api/resumes/status/export-excel` | 현황 Excel 다운로드 |
| GET | `/api/db/health` , `/api/db/counts` | DB 연결 점검 / 테이블 row 수 |

---

## 이력서 분석 점수 산출 기준

현재 이력서 분석 점수는 100점 만점으로 계산됩니다.

점수 구성은 다음과 같습니다.

| 항목 | 배점 | 계산 방식 |
|---|---:|---|
| 필수 기술 매칭 | 70점 | 매칭된 필수 기술 수 / 전체 필수 기술 수 × 70 |
| 우대 기술 매칭 | 20점 | 매칭된 우대 기술 수 / 전체 우대 기술 수 × 20 |
| AI 종합 판단 | 10점 | OpenAI가 반환한 ai_judgment_score 값을 사용 |

현재 기술 매칭은 이력서에서 추출된 기술 목록과 JD에 등록된 기술명을 비교하여 계산합니다.
비교 방식은 기술명을 소문자로 변환하고 공백을 제거한 뒤 정확히 일치하는지 확인하는 방식입니다.
현재는 부분 일치, 유사어, 동의어 매칭은 적용되어 있지 않습니다.

필수 기술 또는 우대 기술 목록이 비어 있는 경우 해당 항목은 0점으로 처리됩니다.
최종 점수는 필수 기술 점수, 우대 기술 점수, AI 종합 판단 점수를 합산하여 계산됩니다.

(구현 위치: `app/services/matching_service.py` 의 `calculate_match`, `app/services/resume_analysis_service.py` 의 `_run_ai`)

---

## JD 기준 점수(threshold_score) 안내

-- 제거

JD 등록 화면에는 `threshold_score`라는 기준 점수 필드가 있습니다.

현재 이 값은 "참고용 기준값"으로만 저장되며, 실제 이력서 분석 점수 계산이나 추천 판정에는 사용되지 않습니다.
기본값은 60점입니다.

현재 추천 판단은 JD별 기준 점수가 아니라 아래 고정 구간으로 결정됩니다.

| 점수 구간 | 추천 문구 |
|---:|---|
| 80점 이상 | 우선 검토 추천 |
| 60점 이상 80점 미만 | 추가 검토 필요 |
| 60점 미만 | 낮은 적합도 |

즉, 현재 버전에서는 JD 등록 시 기준 점수를 변경해도 분석 결과의 추천 문구에는 영향을 주지 않습니다.

> 향후 `threshold_score` 를 실제 추천 판단에 반영하는 개선안은 [`docs/TODO.md`](docs/TODO.md) 의
> "JD 기준 점수 기반 추천 판단 로직 개선" 항목을 참고하세요.

---

## 3. 프로젝트 구조

```text
resume-auto-analyzer/
├─ app/                      # 애플리케이션 코드
│  ├─ main.py                # FastAPI 엔트리포인트 (라우터 등록 / 환경변수 / startup)
│  ├─ api/                   # 라우터 (FastAPI @router)
│  ├─ services/              # 비즈니스 로직 (Drive/LLM/분석/업로드/DB 서비스 등)
│  ├─ core/                  # 설정(config.py) / 경로 유틸(paths.py)
│  ├─ db/                    # SQLAlchemy 세션 / 모델
│  ├─ schemas/               # Pydantic DTO
│  ├─ static/                # 프론트(JS/CSS)
│  └─ templates/             # 프론트(HTML, 단일 페이지)
├─ docs/                     # 문서 (TODO.md / WORKFLOW.md)
├─ secrets/google/           # Google OAuth credentials.json / token.json (Git 제외)
├─ certs/                    # 회사 Root CA (company-root-ca.crt)
├─ data/                     # 런타임 로컬 저장소/캐시 (Git 제외)
├─ alembic/ , alembic.ini    # DB 마이그레이션
├─ Dockerfile
├─ docker-compose.yml
├─ .env / .env.example       # 환경변수 (.env 는 Git 제외)
├─ pyproject.toml , uv.lock  # uv 패키지 관리
└─ run.sh
```

---

## 4. 환경변수

`.env` 에서 읽습니다. `.env.example` 를 복사해 작성하세요. **실제 키/비밀번호는 절대 커밋하지 않습니다.**

```env
# OpenAI (JD 추천 / 이력서 분석)
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4.1-mini

# PostgreSQL
DB_HOST=your-db-host
DB_PORT=5432
DB_NAME=your-db-name
DB_USER=your-db-user
DB_PASSWORD=your-db-password
DB_SCHEMA=resume_ai
# DATABASE_URL 이 있으면 DB_* 보다 우선 사용됩니다.
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST:5432/DBNAME

# Google OAuth 파일 경로 (Docker: 컨테이너 절대경로 / 로컬: 상대경로 또는 미설정 시 루트 fallback)
GOOGLE_CREDENTIALS_PATH=/app/secrets/google/credentials.json
GOOGLE_TOKEN_PATH=/app/secrets/google/token.json

# SSL CA 번들 (회사망/Docker. 미설정 시 코드가 /etc/ssl/certs/ca-certificates.crt 기본값 사용)
SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
HTTPLIB2_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
```

- **`OPENAI_MODEL`** 미설정 시 코드 기본값 `gpt-4.1-mini`.
- **`DATABASE_URL` 우선순위**: `app/core/config.py` 기준 **`DATABASE_URL` 이 있으면 `DB_*` 보다 우선**해서 그대로 사용됩니다. 없을 때만 `DB_HOST/PORT/NAME/USER/PASSWORD` 를 조합합니다.
  - ⚠️ `DATABASE_URL` 에 (예전) 공인 IP 가 남아 있으면 `DB_HOST` 를 바꿔도 계속 그 IP 로 접속을 시도하니 주의하세요. ([10. DB 연결 주의사항](#10-db-연결-주의사항) 참고)
- **Google 경로**: 절대경로는 그대로, 상대경로는 프로젝트 루트 기준으로 해석합니다. 값을 비우면 프로젝트 루트의 `credentials.json` / `token.json` 으로 fallback 합니다. (`app/core/paths.py`)
- **SSL CA**: `SSL_CERT_FILE` > `REQUESTS_CA_BUNDLE` 순으로 사용하며, 둘 다 없으면 `/etc/ssl/certs/ca-certificates.crt` 를 씁니다. ([8. SSL/CA](#8-sslca-인증서-설명) 참고)

---

## DB 초기화 / 마이그레이션 (Alembic)

DB 스키마는 **Alembic 마이그레이션으로 일원화**되어 있습니다. 빈 PostgreSQL DB(또는 빈 `resume_ai` 스키마)에서 아래 한 번으로 서비스에 필요한 **모든 테이블/컬럼/제약/인덱스**가 생성됩니다.

```bash
uv run alembic upgrade head
```

- `resume_ai` 스키마가 없으면 `alembic/env.py` 가 먼저 생성합니다. 접속 URL 은 `.env`(`DATABASE_URL` 또는 `DB_*`)에서 읽습니다. (`alembic.ini` 에 비밀번호를 두지 않음)
- 상태 확인: `uv run alembic current` / `uv run alembic history`.
- 생성 테이블(resume_ai, 9개): `users`, `departments`, `job_descriptions`(legacy), `dept_drive_folders`, `job_postings`, `job_posting_jds`, `resume_upload_batches`, `resume_files`, `resume_analysis_results`.

### 더 이상 수동 SQL 을 먼저 실행할 필요가 없습니다
과거에는 `0001` 이후 `docs/sql/2026-06-12-*.sql` 을 **수동 실행**해야 했지만, 이제 그 내용이 마이그레이션에 편입되었습니다.

| revision | 내용 | 원본 SQL |
| --- | --- | --- |
| `0002_create_users_table` | `users` 테이블 | (수동 SQL 없음 — 모델 기준 신규 편입) |
| `0003_create_job_postings_and_jds` | `job_postings` + `job_posting_jds` | `docs/sql/2026-06-12-posting-jd.sql` (1·2) |
| `0004_add_posting_jd_columns` | `resume_files`/`resume_analysis_results` 의 `posting_id`/`jd_id`/`jd_snapshot` | `docs/sql/2026-06-12-posting-jd.sql` (3·4) |
| `0005_job_posting_dept_nullable` | `job_postings.department_id` nullable | `docs/sql/2026-06-12-job-postings-dept-nullable.sql` |

- **신규 환경**: `alembic upgrade head` **만** 실행하면 됩니다(수동 SQL 실행 불필요).
- `docs/sql/*.sql` 은 **참고용(원본 기록)** 으로만 남깁니다.

### 기존(운영/개발) DB — 이미 수동 SQL 이 적용된 경우
`0002~0005` 는 모두 idempotent(`IF NOT EXISTS` / `DROP NOT NULL`) 라 아래 중 하나면 됩니다.
- **권장**: `uv run alembic upgrade head` — 이미 존재하는 객체는 건너뛰고 alembic 버전만 `0005` 로 전진합니다. (기존 DB 시뮬레이션으로 무충돌 검증 완료)
- **대안(무DDL)**: DB 가 이미 `0005` 상태와 동일하다고 확신하면 `uv run alembic stamp head` 로 버전만 맞춥니다. ⚠️ 운영 DB 에는 **실제 스키마를 확인한 뒤에만** 사용하세요.

> 참고: `users` 테이블은 과거 "이미 생성되어 있다고 가정"했으나 이제 `0002` 로 편입되었습니다. `job_postings/job_posting_jds` 의 FK 와 일부 인덱스(예: `created_at DESC`)는 **DB(마이그레이션)에만 존재**하고 ORM 모델에는 soft-reference 정책상 선언하지 않습니다 — 이 상태에서는 `alembic revision --autogenerate` 가 해당 FK/인덱스 제거를 제안할 수 있으니 **자동생성 대신 손으로 리비전을 작성**하세요. (자세한 내용: [`docs/work-log/2026-07-07-alembic-schema-sync.md`](docs/work-log/2026-07-07-alembic-schema-sync.md))

---

## 사람인 디딤(주) 공고 자동 수집 (배치)

사람인 **'디딤' 검색 결과**를 주기적으로 확인해 **디딤(주)** 의 신규 공고를 자동으로 `job_postings` 에 등록하고, **JD 분석(상세 URL 분석 + JD 저장 + Drive 폴더 생성)은 Celery worker 가 비동기로 처리**합니다. 상세 URL 분석/JD 저장은 **기존 로직(`job_extract_service.extract_from_url`, `job_posting_service.upsert_jd`)을 그대로 재사용**하므로 수동 등록과 동일한 결과가 나옵니다.

**처리 흐름** (1차: JD 분석 비동기화)
```text
[수동 API 또는 Scheduler(주석)]
사람인 검색결과 수집 → 회사명 "디딤(주)"(normalize 후 exact) 필터 → detail_url(rec_idx) 정규화
→ platform_posting_url 기준 기존 공고 중복 확인 → 신규만 job_postings insert(status=DRAFT)
→ analyze_job_posting_jd_task.delay(posting_id) 로 큐 적재 → 공고 status=JD_QUEUED

[Celery worker · job_discovery 큐]
posting_id 로 공고 재조회 → status JD_PROCESSING → job_extract_service.extract_from_url(detail_url)
→ job_posting_service.upsert_jd(JD 저장 + Drive 공고 폴더 생성) → status JD_READY (실패 시 JD_FAILED)
```
- **큐에는 detail_url 이 아니라 `posting_id` 만** 넣습니다(worker 가 DB 에서 재조회 — 중복/상태/실패 처리 용이).
- 공고 하나가 실패해도 나머지는 계속 처리합니다(공고 단위 격리). 자동 수집 공고는 검토 전이므로 초기 **status=DRAFT**, 부서/팀은 **미지정(None)**.
- JD 분석 상태값(공고 `status`, worker 전용): `JD_QUEUED → JD_PROCESSING → JD_READY / JD_FAILED`. (사용자 편집용 `DRAFT/OPEN/CLOSED/INACTIVE` 목록과 분리 — UI 상태 목록 불변)
- worker 는 idempotent: 이미 active JD 가 있거나 `JD_READY` 면 skip. 일시적 실패(fetch/OpenAI rate·network, Drive 인증)는 제한 재시도.

**수동 실행 API** (권한: ADMIN/MANAGER, VIEWER 403)
```bash
POST /api/jobs/discover/saramin/didim
```
응답 예: `{ "source": "SARAMIN", "collected_count", "matched_company_count", "new_count", "queued_count", "skipped_duplicate_count", "failed_count", "items": [{ "posting_id", "title", "detail_url", "status": "JD_QUEUED" }] }`.

> **JD 분석만 비동기화한 1차 작업**입니다. 이력서 분석(`/api/resumes/analyze-posting` 등)의 Celery 전환은 2차 작업입니다(레거시 부서 중심 `analyze_pending`/`batch_service` 는 큐 대상 아님).

**스케줄러 (1시간 주기) — 현재 주석 처리 상태**
- `app/services/scheduler_service.py` 에 진입점 `run_saramin_didim_discovery()` 와 1시간 interval 등록 코드가 있으나, **실제 자동 실행은 주석 처리**되어 있습니다(서버 startup 에서 동작하지 않음).
- 운영 반영 시: ① `pyproject.toml` 에 `apscheduler` 추가 후 `uv sync` → ② `scheduler_service.py` 의 `start_scheduler()` 주석 해제 → ③ `SARAMIN_DISCOVERY_ENABLED=true` 인 경우에만 startup 에서 호출. (자세한 위치는 `scheduler_service.py` 상단 주석)

**관련 설정**(`.env`, 미설정 시 코드 기본값 사용): `SARAMIN_DIDIM_SEARCH_URL`, `SARAMIN_DIDIM_KEYWORD`(디딤), `SARAMIN_DIDIM_COMPANY_NAME`(디딤(주)), `SARAMIN_DISCOVERY_ENABLED`(false).

> 사람인 HTML 구조가 바뀌면 검색결과 파서(`app/services/saramin_job_collect_service.py`)를 수정해야 합니다. 순수 JS 렌더링 전용 페이지는 정적 수집 한계가 있어 Playwright fallback 은 이번 범위에서 제외했습니다. (`docs/work-log/2026-07-07-saramin-job-discovery-batch.md`)

---

## Redis / Celery (비동기 작업 큐)

비동기 작업을 처리하기 위해 **Redis(broker/result) + Celery worker** 를 사용합니다. 두 개의 큐로 분리되어 있습니다.
- **`job_discovery`** (1차): 사람인 신규 공고 JD 분석 (`analyze_job_posting_jd_task`).
- **`resume_analysis`** (2차): 공고 기준 이력서 분석 (`analyze_resume_posting_task`).

**이력서 분석은 비동기(Celery)로 처리됩니다.** `POST /api/resumes/analyze-posting`(및 `analyze-selected`/`analyze-all`)는 분석을 직접 실행하지 않고 큐에 등록한 뒤 **즉시 `QUEUED` 응답**(`task_id`, `queue`, `pending_count`)을 반환합니다. worker 가 `resume_analysis` 큐에서 기존 `resume_analysis_service.analyze_posting` 을 그대로 재사용해 Drive download → PDF/DOCX 파싱 → OpenAI 분석 → 점수 계산 → completed/failed 이동 → DB 저장을 수행합니다(파일 단위 성공/실패 격리 유지). 진행/결과는 **기존 '이력서 현황' 화면**에서 파일 상태(PENDING/PROCESSING/COMPLETED/FAILED)로 확인합니다(자동 polling 미도입 — 새로고침).
- 중복 방지: 같은 공고에 PROCESSING 파일이 있으면 `ALREADY_PROCESSING`, PENDING 파일이 없으면 `NO_PENDING` 로 응답하고 enqueue 하지 않습니다. `analyze-all`(ADMIN)은 대기 공고별로 task 를 나눠 enqueue 해 요청 타임아웃을 피합니다.

**환경변수**(`.env`, 실제 URL/비밀번호는 `.env` 에만): `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CELERY_TASK_DEFAULT_QUEUE`(job_discovery), `CELERY_TIMEZONE`(Asia/Seoul), `CELERY_WORKER_PREFETCH_MULTIPLIER`(1), `CELERY_TASK_ACKS_LATE`(true).
- Docker Compose 내부에서는 broker 를 **`redis://redis:6379/0`**(서비스명), 로컬 직접 실행은 `redis://localhost:6379/0`.

**로컬 실행**
```bash
# 1) Redis 기동 (예: docker)
docker run -d --name redis -p 6379:6379 redis:7-alpine
redis-cli ping        # -> PONG

# 2) API 서버
uv run uvicorn app.main:app --reload

# 3) Celery worker (별도 터미널) — 두 큐 함께 처리
uv run celery -A app.core.celery_app.celery_app worker --loglevel=INFO -Q job_discovery,resume_analysis
```

**Docker Compose 실행** (`docker-compose.yml` 에 `redis` + `resume-ai-worker` 추가됨)
```bash
docker compose up -d --build          # redis, resume-ai(app), resume-ai-worker 함께 기동
docker compose logs -f resume-ai-worker
```
- worker 는 app 과 **동일 이미지/`.env`/볼륨**(google secrets, data)을 사용하며 DB/OpenAI/Google Drive/회사 CA 에 동일하게 접근합니다.
- 기본적으로 redis 는 내부 네트워크로만 접근합니다(host 포트 미노출 — 로컬 디버깅 시 compose 의 redis `ports` 주석 해제).

- worker 는 두 큐(`job_discovery,resume_analysis`)를 함께 처리합니다(선택 A). 부하가 커지면 `resume_analysis` 전용 worker 로 분리할 수 있습니다(후속 — `docs/TODO.md`).

> 사람인 수집 API 를 호출하면 신규 공고가 `JD_QUEUED` 로 큐에 적재되고, worker 가 JD 를 생성해 `JD_READY` 로 만듭니다. 이력서 분석 API 는 `QUEUED` 를 반환하고 worker 가 처리합니다. Redis/worker 가 없으면 큐 적재가 실패합니다(503 / 공고는 `JD_FAILED`).

---

## 5. 로컬 실행 방법 (uv)

```bash
uv sync
uv run uvicorn app.main:app --reload
```

- 화면: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`

**Google credentials/token 경로 주의(로컬)**
- 로컬에서는 `.env` 에 상대경로(예: `GOOGLE_CREDENTIALS_PATH=secrets/google/credentials.json`)를 쓰거나 값을 비워 프로젝트 루트 fallback 을 쓸 수 있습니다.
- `secrets/google/` 아래에 `credentials.json` 을 두고, 최초 Drive 호출 시 출력되는 OAuth URL 로 인증하면 `token.json` 이 생성됩니다. (WSL 은 브라우저가 없어 URL 을 Windows 브라우저에서 직접 엽니다.)

---

## 6. Docker 실행 방법 (Docker Compose)

```bash
docker compose build
docker compose up -d
docker compose logs -f
```

- 포트 매핑: **호스트 `28080` → 컨테이너 `8000`**
- 화면: `http://localhost:28080`
- Swagger: `http://localhost:28080/docs`

**준비물**
- `.env` (컨테이너 기준 절대경로 권장: `GOOGLE_CREDENTIALS_PATH=/app/secrets/google/credentials.json`, `GOOGLE_TOKEN_PATH=/app/secrets/google/token.json`)
- `secrets/google/credentials.json`, `secrets/google/token.json` (volume 마운트: `./secrets/google:/app/secrets/google`)
- `certs/company-root-ca.crt` (회사망 빌드 시 필요 — [8. SSL/CA](#8-sslca-인증서-설명) 참고)

> `.env` / `secrets` / `credentials.json` / `token.json` 은 이미지에 포함하지 않고 `env_file` / volume 으로만 runtime 에 주입됩니다. (`.dockerignore` 로 빌드 컨텍스트에서도 제외)

---

## 7. NCP 서버 배포 (Git 없이 tar.gz + scp)

현재는 Git 연동 없이 **로컬에서 tar.gz 로 묶어 scp 로 서버에 올리고** Docker Compose 로 실행합니다.

```bash
# 1) 로컬: 불필요 파일 제외하고 압축 (secrets/.env 포함 여부는 보안정책에 맞게 결정)
tar \
  --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
  --exclude='data' \
  -czf resume-ai.tar.gz .

# 2) 로컬 -> 서버 업로드
scp resume-ai.tar.gz USER@NCP_SERVER_IP:/tmp/

# 3) 서버: 배포 경로에 해제
ssh USER@NCP_SERVER_IP
sudo mkdir -p /opt/resume-auto-analyzer
sudo tar -xzf /tmp/resume-ai.tar.gz -C /opt/resume-auto-analyzer
cd /opt/resume-auto-analyzer

# 4) .env / secrets/google / certs 준비 (서버에서 직접 배치)
#    - .env (서버용 값: DB_HOST/host.docker.internal, GOOGLE_*_PATH=/app/... 등)
#    - secrets/google/credentials.json, secrets/google/token.json
#    - certs/company-root-ca.crt (회사망일 때)

# 5) 빌드 & 실행
docker compose build
docker compose up -d
docker compose logs -f

# 6) NCP ACG(방화벽)에서 28080 포트 인바운드 오픈

# 7) 서버 내부 점검
curl -i http://localhost:28080/
curl -s http://localhost:28080/api/db/health

# 8) 브라우저: http://NCP_SERVER_IP:28080
```

> 배포 경로 권장: `/opt/resume-auto-analyzer`. 향후 배포 자동화(`deploy.sh`, Git/GHCR/Jenkins 등)는 [`docs/TODO.md`](docs/TODO.md) 의 "배포/운영 개선" 참고.

---

## 8. SSL/CA 인증서 설명

회사망에서는 **Fortinet SSL inspection** 때문에 외부 HTTPS 인증서 체인에 회사 Root CA(self-signed) 가 끼어들어, 회사 CA 를 신뢰하지 않으면 검증에 실패합니다.

- **로컬 회사망/WSL/Docker** 에서는 Fortinet(회사) Root CA 가 필요할 수 있습니다.
- **NCP 서버** 에서는 보통 Google Trust Services 등 공개 CA 가 직접 보이므로 Fortinet CA 가 필수가 아닐 수 있습니다. (환경에 따라 다름)
- 단, 현재 `Dockerfile` 이 `certs/company-root-ca.crt` 를 `COPY` 하므로 **빌드하려면 이 파일이 존재해야 합니다.** (회사 CA 가 필요 없는 환경이면 해당 라인/파일을 환경에 맞게 조정)

**Dockerfile 의 CA 설정(요지)**
- `apt-get install ... ca-certificates`
- `COPY certs/company-root-ca.crt /usr/local/share/ca-certificates/company-root-ca.crt`
- `RUN update-ca-certificates` → 시스템 번들 `/etc/ssl/certs/ca-certificates.crt` 에 회사 CA 포함
- `ENV SSL_CERT_FILE`, `ENV REQUESTS_CA_BUNDLE` = `/etc/ssl/certs/ca-certificates.crt`

**환경변수 의미**
- `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE`: Python(requests/httpx 등)이 신뢰할 CA 번들 경로.
- `HTTPLIB2_CA_CERTS`: `httplib2` 가 참고하는 CA 경로(앱에서도 별도 명시).

**httplib2 에 CA 를 명시한 배경**
- `curl` 은 성공하는데 **Google API client(googleapiclient → google_auth_httplib2 → httplib2)** 호출만 `SSL: CERTIFICATE_VERIFY_FAILED (self-signed certificate in certificate chain)` 로 실패하는 문제가 있었습니다.
- `httplib2` 가 시스템 CA 번들을 제대로 쓰지 못해서였고, **Drive service 생성 시 `httplib2.Http(ca_certs=...)` + `AuthorizedHttp` 를 명시**해 해결했습니다. (`app/services/google_drive_service.py` 의 `build_drive`)

> 회사 인증서 내용(파일 본문) 자체는 문서에 넣지 않습니다.

---

## 9. Google 계정 / Token 교체 방법

향후 HR 전용/resume 전용 Google 계정으로 Drive 연동 계정을 바꿀 수 있습니다.

1. 새 계정으로 OAuth 인증을 수행해 새 `token.json` 을 생성합니다. (필요 시 `credentials.json` 도 새 OAuth 클라이언트로 교체)
2. 서버의 `secrets/google/credentials.json`, `secrets/google/token.json` 을 교체합니다.
3. 컨테이너 재시작:
   ```bash
   docker compose restart resume-ai
   ```
4. **새 계정에 대상 Google Drive 폴더(resume-demo-root 등) 접근 권한이 있어야** 합니다. (없으면 폴더 조회/업로드 실패)
5. 현재 연결된 Drive 계정 확인은 `service.about().get(fields="user")` 로 가능합니다. (예: 디버깅 스크립트에서 호출)

---

## 10. DB 연결 주의사항

NCP 서버에서 **앱 컨테이너가 같은 서버에 떠 있는 PostgreSQL** 에 붙을 때, 공인 IP 대신 `host.docker.internal` 을 써야 할 수 있습니다.

- `.env` 에서 `DB_HOST=host.docker.internal` 사용.
- `docker-compose.yml` 의 서비스에 `extra_hosts` 추가가 필요할 수 있습니다.
  ```yaml
  services:
    resume-ai:
      extra_hosts:
        - "host.docker.internal:host-gateway"
  ```
  > 현재 `docker-compose.yml` 에는 `extra_hosts` 가 들어있지 않습니다. 같은 서버 DB 로 붙는 환경이면 위 설정을 추가하세요. (이 문서는 코드를 변경하지 않습니다.)
- ⚠️ **`DATABASE_URL` 이 `DB_HOST` 보다 우선** 적용됩니다. `.env` 에 `DATABASE_URL` 이 (예전) 공인 IP 로 남아 있으면 `DB_HOST` 를 바꿔도 계속 잘못된 IP 로 접속을 시도하니, **둘 중 하나로만** 관리하세요.
- **TCP connect OK ≠ DB 로그인/쿼리 OK**: 포트가 열려 접속만 되는 것과 실제 인증/스키마 권한이 맞는 것은 다릅니다. `/api/db/health` 로 실제 쿼리까지 확인하세요.

---

## 11. 보안 주의사항

- `.env` 는 Git 에 올리지 않습니다. (`.gitignore` 포함)
- `credentials.json`, `token.json`, `secrets/` 는 Git 에 올리지 않습니다.
- **OpenAI API Key 노출 주의** — 노출되면 즉시 **rotate(재발급)** 하세요.
- 서버의 `.env`, `credentials.json`, `token.json` 은 파일 권한을 제한(예: `chmod 600`)하세요.
- NCP **ACG(방화벽)** 에서 SSH(22)/앱(28080)/DB(5432) 접근을 **필요한 IP 로만** 제한하세요.
- **DB 5432 를 외부 전체(0.0.0.0/0) 오픈 금지.**
- `token.json` 에는 `refresh_token` 이 포함될 수 있으므로 민감정보로 취급합니다.

---

## 12. 트러블슈팅 (실제 겪은 문제)

- **Docker 에서 Google OAuth/Drive SSL 실패** — `SSL: CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain` (Fortinet CA).
  - `curl` 은 성공하지만 `googleapiclient`/`httplib2` 호출만 실패 → **`httplib2.Http(ca_certs=/etc/ssl/certs/ca-certificates.crt)` + `AuthorizedHttp`** 로 해결. (`build_drive`)
- **`app/main.py` 의 `SSL_CERT_FILE` 하드코딩 문제** — 과거 `forti-ca.crt` 절대경로를 직접 지정해 컨테이너에 파일이 없으면 `FileNotFoundError`. 현재는 `/etc/ssl/certs/ca-certificates.crt` 로 `os.environ.setdefault` 하도록 정리됨.
- **NCP 컨테이너 DB 연결 timeout** — `DB_HOST` 를 공인 IP 로 둬서 같은 서버 DB 에 못 붙음 → `host.docker.internal` + `extra_hosts` 로 해결.
- **`DATABASE_URL` 우선순위 함정** — `DATABASE_URL` 이 `DB_HOST` 보다 우선이라, `.env` 의 옛 공인 IP `DATABASE_URL` 때문에 계속 잘못된 IP 로 붙던 문제. → `DATABASE_URL` 수정 또는 제거.
- **DB 점검 API** — DB 연결은 `/api/db/health` (그리고 `/api/db/counts`) 로 확인합니다. (없는 엔드포인트로 확인하려다 헷갈리지 않도록 실제 존재하는 API 사용)
- **Google token 계정 변경** — 계정을 바꾸면 **그 계정에 Drive 폴더 권한이 있어야** 합니다. ([9. 계정/Token 교체](#9-google-계정--token-교체-방법) 참고)
- **OpenAI `APIConnectionError`** — 회사망 CA 미신뢰 시 `CERTIFICATE_VERIFY_FAILED`. (curl 성공/SDK 실패면 CA 번들 문제일 가능성. 서버 로그 `[llm] error type/message` 확인)

---

## 부록. 참고 명령어

```bash
# 로컬 실행
uv run uvicorn app.main:app --reload

# Docker
docker compose build && docker compose up -d && docker compose logs -f

# 점검
curl -s http://localhost:28080/api/db/health
curl -i http://localhost:28080/
```
