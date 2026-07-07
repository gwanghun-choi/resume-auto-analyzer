-- =============================================================================
-- 공고/JD 중심 구조 전환 - DB 변경 (resume_ai 스키마 전용)
-- 작성일: 2026-06-12
-- 주의: 이 스크립트는 resume_ai 스키마만 변경합니다. 다른 스키마는 절대 건드리지 않습니다.
-- 실행: psql ... -f docs/sql/2026-06-12-posting-jd.sql  (DB 점검 후 직접 실행)
-- 모두 IF NOT EXISTS 라 여러 번 실행해도 안전(idempotent)합니다.
-- =============================================================================

-- 안전장치: resume_ai 스키마 안에서만 작업
SET search_path TO resume_ai, public;

-- -----------------------------------------------------------------------------
-- 1) 공고: resume_ai.job_postings
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS resume_ai.job_postings (
    id                        bigserial PRIMARY KEY,
    title                     varchar(255) NOT NULL,
    department_id             varchar(50)  NOT NULL,             -- departments.id(문자열) 참조 (users 스타일: 하드 FK 없음)
    platform_code             varchar(50)  NULL,                 -- SARAMIN / JOBKOREA / WANTED / ETC
    platform_posting_url      text         NULL,
    status                    varchar(30)  NOT NULL DEFAULT 'OPEN',  -- DRAFT / OPEN / CLOSED / INACTIVE
    drive_folder_id           varchar(255) NULL,
    drive_inbox_folder_id     varchar(255) NULL,
    drive_completed_folder_id varchar(255) NULL,
    drive_failed_folder_id    varchar(255) NULL,
    created_by                bigint       NULL,
    created_at                timestamp    NOT NULL DEFAULT now(),
    updated_at                timestamp    NOT NULL DEFAULT now(),
    CONSTRAINT fk_job_postings_created_by
        FOREIGN KEY (created_by) REFERENCES resume_ai.users(id) ON DELETE SET NULL
);
COMMENT ON TABLE  resume_ai.job_postings IS '채용 공고. 외부 플랫폼 공고와 1:1 대응(현재). 부서는 권한 기준으로 유지.';
COMMENT ON COLUMN resume_ai.job_postings.department_id IS '공고 소속 부서 id (departments.id). 권한 필터 기준.';
COMMENT ON COLUMN resume_ai.job_postings.platform_code IS '외부 플랫폼 코드: SARAMIN/JOBKOREA/WANTED/ETC';
COMMENT ON COLUMN resume_ai.job_postings.status IS '공고 상태: DRAFT/OPEN/CLOSED/INACTIVE';

CREATE INDEX IF NOT EXISTS ix_job_postings_department_id ON resume_ai.job_postings (department_id);
CREATE INDEX IF NOT EXISTS ix_job_postings_status        ON resume_ai.job_postings (status);
CREATE INDEX IF NOT EXISTS ix_job_postings_platform_code ON resume_ai.job_postings (platform_code);
CREATE INDEX IF NOT EXISTS ix_job_postings_created_at    ON resume_ai.job_postings (created_at DESC);

-- -----------------------------------------------------------------------------
-- 2) JD 상세: resume_ai.job_posting_jds  (현재 1공고=1 active JD, 서비스에서 강제)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS resume_ai.job_posting_jds (
    id               bigserial PRIMARY KEY,
    posting_id       bigint       NOT NULL,
    title            varchar(255) NULL,
    required_skills  jsonb        NULL,        -- MatchingService 호환: 문자열 리스트
    preferred_skills jsonb        NULL,
    jd_content       text         NULL,
    is_active        boolean      NOT NULL DEFAULT true,
    created_by       bigint       NULL,
    created_at       timestamp    NOT NULL DEFAULT now(),
    updated_at       timestamp    NOT NULL DEFAULT now(),
    CONSTRAINT fk_job_posting_jds_posting
        FOREIGN KEY (posting_id) REFERENCES resume_ai.job_postings(id) ON DELETE CASCADE,
    CONSTRAINT fk_job_posting_jds_created_by
        FOREIGN KEY (created_by) REFERENCES resume_ai.users(id) ON DELETE SET NULL
);
COMMENT ON TABLE resume_ai.job_posting_jds IS '공고에 연결된 JD 상세. 현재 공고당 1개 active JD만 허용(서비스 레벨). DB unique 제약은 두지 않음(향후 1공고 N JD 확장 대비).';

CREATE INDEX IF NOT EXISTS ix_job_posting_jds_posting_id ON resume_ai.job_posting_jds (posting_id);
CREATE INDEX IF NOT EXISTS ix_job_posting_jds_is_active  ON resume_ai.job_posting_jds (is_active);

-- -----------------------------------------------------------------------------
-- 3) resume_files: posting_id / jd_id 추가 (dept_id 는 유지 — 권한/호환)
--    (실제 컬럼명은 dept_id 임. department_id 아님)
-- -----------------------------------------------------------------------------
ALTER TABLE resume_ai.resume_files ADD COLUMN IF NOT EXISTS posting_id bigint NULL;
ALTER TABLE resume_ai.resume_files ADD COLUMN IF NOT EXISTS jd_id      bigint NULL;
COMMENT ON COLUMN resume_ai.resume_files.posting_id IS '업로드된 공고 id (job_postings.id). 기존 데이터는 NULL=미매핑.';
COMMENT ON COLUMN resume_ai.resume_files.jd_id      IS '업로드 시점 공고의 active JD id (job_posting_jds.id).';

CREATE INDEX IF NOT EXISTS ix_resume_files_posting_id ON resume_ai.resume_files (posting_id);
CREATE INDEX IF NOT EXISTS ix_resume_files_jd_id      ON resume_ai.resume_files (jd_id);

-- -----------------------------------------------------------------------------
-- 4) resume_analysis_results: posting_id / jd_id / jd_snapshot 추가
-- -----------------------------------------------------------------------------
ALTER TABLE resume_ai.resume_analysis_results ADD COLUMN IF NOT EXISTS posting_id  bigint NULL;
ALTER TABLE resume_ai.resume_analysis_results ADD COLUMN IF NOT EXISTS jd_id       bigint NULL;
ALTER TABLE resume_ai.resume_analysis_results ADD COLUMN IF NOT EXISTS jd_snapshot jsonb  NULL;
COMMENT ON COLUMN resume_ai.resume_analysis_results.posting_id  IS '분석 기준 공고 id.';
COMMENT ON COLUMN resume_ai.resume_analysis_results.jd_id       IS '분석 기준 JD id.';
COMMENT ON COLUMN resume_ai.resume_analysis_results.jd_snapshot IS '분석 당시 JD 스냅샷(title/required_skills/preferred_skills/jd_content).';

CREATE INDEX IF NOT EXISTS ix_analysis_results_posting_id     ON resume_ai.resume_analysis_results (posting_id);
CREATE INDEX IF NOT EXISTS ix_analysis_results_jd_id          ON resume_ai.resume_analysis_results (jd_id);
CREATE INDEX IF NOT EXISTS ix_analysis_results_resume_file_id ON resume_ai.resume_analysis_results (resume_file_id);

-- -----------------------------------------------------------------------------
-- 5) (선택) 더미 데이터 — 필요 시에만 주석 해제. 민감정보 없음. resume_ai 한정.
--    created_by 는 admin 계정 id 로 바꿔서 사용하세요.
-- -----------------------------------------------------------------------------
-- INSERT INTO resume_ai.job_postings (title, department_id, platform_code, platform_posting_url, status, created_by)
-- VALUES ('[DX센터] Java/Spring 백엔드 개발자 채용', 'D00173', 'SARAMIN', 'https://example.com/posting/1', 'OPEN', NULL);
