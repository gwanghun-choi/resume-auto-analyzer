from sqlalchemy import Column, String, Text, Boolean, BigInteger, TIMESTAMP, Index

from app.db.base import Base, TimestampMixin

# users: 로그인 사용자 계정. (resume_ai.users 테이블, DDL 은 이미 생성되어 있다고 가정)
# - 부서 참조 컬럼은 department_id 이며 departments.id(D00035 같은 문자열) 를
#   참조하므로 String 입니다. (Integer 아님)
# - password_hash: 현재 단계에서는 평문이 들어있다고 가정하고 평문 비교합니다.
#   TODO: 운영 전 bcrypt/argon2 해시 검증으로 교체해야 합니다.


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_login_id", "login_id"),
        Index("ix_users_email", "email"),
        {"comment": "로그인 사용자 계정 테이블."},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True,
                comment="사용자 PK (BIGSERIAL)")
    login_id = Column(String(100), nullable=False, unique=True, comment="로그인 ID")
    email = Column(String(255), nullable=False, unique=True, comment="이메일")
    name = Column(String(100), nullable=False, comment="사용자 표시 이름")
    password_hash = Column(Text, nullable=False,
                           comment="비밀번호. 현재 단계는 평문 비교(운영 전 해시 검증으로 교체 예정)")
    role_code = Column(String(30), nullable=False, comment="역할 코드 (ADMIN/MANAGER/VIEWER)")
    department_id = Column(String(50), nullable=True,
                           comment="소속 부서 ID. departments.id(문자열) 참조")
    is_active = Column(Boolean, nullable=False, server_default="true", comment="활성 여부")
    last_login_at = Column(TIMESTAMP, nullable=True, comment="마지막 로그인 시각")
