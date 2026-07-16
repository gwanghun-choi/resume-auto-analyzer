# [2026-07-07] 사람인 대상 회사 신규 공고 자동 수집 배치

## 1. 작업 배경

수동으로는 이미 다음이 가능하다: 공고 URL 입력 → URL 상세 추출 → LLM 으로 JD 구조화 → 공고/JD 저장 → JD 저장 성공 시 Drive 공고 폴더 생성.
이번 작업은 이 수동 흐름을 **사람인 검색 결과 기반으로 주기 자동화**하여, 대상 회사의 신규 공고를 자동으로 `job_postings`/`job_posting_jds` 에 등록하는 배치 구조를 추가한다.

## 2. 구현 목표

- 사람인 검색 URL 을 1시간마다 확인하는 배치 구조 추가(실제 스케줄 등록은 주석 처리).
- **상세 URL 분석 로직은 새로 만들지 않고** 기존 `job_extract_service` / `job_posting_service` 를 재사용(수동 실행과 배치 실행이 같은 결과).
- 새로 만드는 핵심은 **검색 결과 목록에서 신규 detail_url 을 찾는 수집기 + 배치 실행 구조**.

## 3. 변경 파일

### 추가
- `app/services/saramin_job_collect_service.py` — 사람인 검색 결과 수집·파싱·회사명 필터·detail_url 정규화.
- `app/services/job_posting_discovery_service.py` — 중복 확인 → 신규 insert → 기존 URL 분석/JD 저장 재사용 → 결과 요약.
- `app/services/scheduler_service.py` — 배치 진입점 `run_saramin_discovery()` + 1시간 interval 등록(주석 처리).
- `docs/work-log/2026-07-07-saramin-job-discovery-batch.md` — 본 문서.

### 수정 (기존 로직 불변, 추가만)
- `app/api/jobs_router.py` — `POST /api/jobs/discover/saramin` 수동 실행 엔드포인트 추가(기존 `extract-from-url` 불변).
- `app/core/config.py` — `SARAMIN_SEARCH_URL`/`_KEYWORD`/`_COMPANY_NAME`/`SARAMIN_DISCOVERY_ENABLED` 설정 추가.
- `.env.example` — 위 설정 예시 추가.
- `README.md` / `docs/WORKFLOW.md` / `docs/TODO.md` — 기능/흐름/TODO 반영.

> 기존 이력서 분석 파이프라인, OpenAI 프롬프트, Google Drive 이동/업로드, 공고/JD 저장 정책, 프론트 화면, API 응답 구조는 **변경하지 않았다**.

## 4. 처리 흐름

```
사람인 검색결과 페이지 정적 수집(job_extract_service._fetch_html 재사용, SSRF 방어)
→ 카드(div.item_recruit) 단위 파싱: 회사명 / 제목(title 속성) / view 링크(rec_idx)
→ 회사명 normalize(공백 제거) 후 exact 필터: 대상 회사 표기(예: `샘플(주)`/`샘플 (주)`/`샘플 주식회사`) 만 통과
→ detail_url 을 rec_idx 기준 표준 URL 로 정규화(추적 query 제거) + external_id="SARAMIN:{rec_idx}"
→ job_postings.platform_posting_url(정확 일치 또는 rec_idx LIKE) 로 중복 확인
→ 신규만: job_extract_service.extract_from_url(detail_url) [기존 로직 재사용: 대상 회사 재검증 + JD 구조화]
→ job_posting_service.create_posting(status=DRAFT, platform=SARAMIN, 부서 미지정)
→ job_posting_service.upsert_jd(..., drive_factory=build_authenticated_drive)
       자격요건→required_skills, 우대사항→preferred_skills, 주요업무→jd_content (parse_skill_text 재사용)
→ JD 저장 성공 시 기존 로직대로 Drive 공고 폴더 생성(한 트랜잭션, 실패 시 JD 저장 롤백)
```

**중복 판단 기준**: 현재 모델에 `external_id` 컬럼이 없어 **무리하게 추가하지 않고** 기존 `platform_posting_url`(정규화 detail_url, rec_idx 포함) 을 기준으로 사용했다. rec_idx 를 `external_id` 성격으로 활용(향후 컬럼 정식화 시 재검토 — TODO).

**실패 격리**: 공고 단위 try/except 로 한 공고가 실패해도 나머지는 계속 처리한다. 실패 step 코드: `search_page_fetch_failed`, `search_page_parse_failed`, `duplicate_job_posting`(skip), `company_filter_no_match`, `job_detail_extract_failed`, `job_posting_insert_failed`, `job_jd_upsert_failed`, `drive_folder_create_failed`.

## 5. 스케줄러 주석 처리 이유

- 요구사항상 **실제 자동 1시간 실행은 이번 작업에서 활성화하지 않는다**(운영 반영 시 주석 해제).
- 현재 프로젝트 dependencies 에 스케줄러 라이브러리(apscheduler)가 없어 **임의로 추가하지 않았다**(불필요한 의존성/대규모 변경 회피). 등록 코드는 apscheduler 예시로 주석 처리하고, 활성화 절차(의존성 추가 → 주석 해제 → startup 조건부 호출)를 파일 상단 주석과 README 에 명시했다.
- `app/main.py` 는 변경하지 않았다(서버 startup 에서 자동 실행되지 않도록).

## 6. 수동 실행 방법

```
POST /api/jobs/discover/saramin
```
- 권한: ADMIN/MANAGER (VIEWER 403). 로그인 세션 필요.
- 응답 예:
```json
{
  "source": "SARAMIN", "keyword": "샘플", "company_filter": "샘플(주)",
  "search_url": "...", "collected_count": 3, "matched_company_count": 2,
  "new_count": 1, "skipped_duplicate_count": 1, "failed_count": 0,
  "items": [ { "title": "...", "detail_url": "...", "rec_idx": "111", "status": "created", "posting_id": 1 } ]
}
```
- 스케줄러(무인) 실행은 `scheduler_service.run_saramin_discovery()` 가 활성 ADMIN 계정 권한으로 같은 service 를 호출한다(수동/배치 동일 경로).

## 7. 검증 결과

일회용 Postgres 컨테이너(`postgres:16-alpine`) + 외부 호출(사람인 fetch/OpenAI/Google Drive) stub 으로 검증. `DATABASE_URL` 은 환경변수로만 주입(운영 `.env` 미변경).

- **단위(순수 함수)**: 회사명 normalize/필터 — `샘플(주)`/`샘플 (주)`/`샘플 주식회사` True, `샘플의원`·`(주)샘플 커뮤니케이션`·`메가샘플(주)` 등 False. detail_url 절대경로/추적 query 제거. 검색결과 HTML 파싱(대상 회사만 매칭).
- **DB 통합**: 1회차 신규 2건 insert(공고 status=DRAFT/platform=SARAMIN, JD required/preferred/jd_content 매핑, Drive 폴더 id 세팅) → 2회차 동일 detail_url 전부 `duplicate` skip(공고 수 불변).
- **실패 격리**: 3건 중 1건 정상 생성, 1건 extract 실패(`job_detail_extract_failed`), 1건 상세 회사 미검증(`company_filter_no_match`) — 배치 중단 없이 나머지 처리, 정상 1건만 insert.

## 8. 주의사항 / 남은 작업

- 스케줄러는 **주석 처리 상태**다. 운영 적용 시: apscheduler 추가 → `start_scheduler()` 주석 해제 → `SARAMIN_DISCOVERY_ENABLED=true` 조건부 startup 호출(다중 워커 중복 실행 주의).
- 사람인 HTML 구조가 바뀌면 `saramin_job_collect_service` 파서(정규식) 수정 필요. 수집 0건/파싱 실패 모니터링 권장.
- 순수 JS 렌더링 전용 페이지는 정적 수집 한계 — **Playwright/Selenium fallback 은 이번 범위 제외**(기존 job_extract 정책과 동일).
- 관리자 화면에서 수집 결과 확인 기능은 후속(현재 API 응답/로그로만).
- 민감정보(OpenAI Key/DB 비밀번호/Google token)·HTML 전체는 로그로 남기지 않는다(실패 URL/step 만).
