-- =============================================================================
-- 공고 부서/팀 선택사항화 - department_id NOT NULL 해제 (resume_ai 스키마 전용)
-- 작성일: 2026-06-12
-- 배경: 공고 등록/수정에서 부서/팀을 선택사항으로 변경(부서 미지정 공고 저장 허용).
-- 주의: resume_ai 스키마만 변경합니다. 컬럼명/타입/다른 컬럼은 변경하지 않습니다(되돌리기 쉬움).
--       재실행해도 안전(이미 nullable 이면 무변화).
-- =============================================================================
SET search_path TO resume_ai, public;

ALTER TABLE resume_ai.job_postings ALTER COLUMN department_id DROP NOT NULL;
COMMENT ON COLUMN resume_ai.job_postings.department_id IS '공고 소속 부서 id (departments.id). 선택사항(미지정 가능). 권한 필터 기준.';

-- 되돌리기(부서 필수로 복귀, 단 NULL 데이터가 없을 때만):
-- ALTER TABLE resume_ai.job_postings ALTER COLUMN department_id SET NOT NULL;
