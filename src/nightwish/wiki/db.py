"""영속성 계층 — SQLAlchemy ORM (로컬 SQLite ↔ Railway Postgres).

`DATABASE_URL` 환경변수로 백엔드를 고른다:
* 미설정 → 로컬 `sqlite:///./nightwish.db`
* Railway Postgres → `postgresql://...` (플랫폼이 자동 주입)

`postgres://`(구형) 접두사는 SQLAlchemy 2.0이 요구하는 `postgresql://`로 정규화한다.
인메모리 SQLite(테스트)는 단일 커넥션을 공유하도록 StaticPool을 쓴다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

Base = declarative_base()


def _normalize_url(url: str) -> str:
    if url.startswith("postgres://"):  # Heroku/Railway 구형 접두사
        url = "postgresql://" + url[len("postgres://"):]
    return url


def make_engine(url: str | None = None):
    """엔진을 만든다. SQLite(파일/메모리) 특수 옵션을 자동 처리."""
    url = _normalize_url(url or os.environ.get("DATABASE_URL", "sqlite:///./nightwish.db"))
    if url.startswith("sqlite"):
        if ":memory:" in url:
            return create_engine(
                url, connect_args={"check_same_thread": False}, poolclass=StaticPool
            )
        return create_engine(url, connect_args={"check_same_thread": False})
    # Postgres 등: 끊긴 커넥션 자동 회복
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine) -> None:
    """테이블을 생성한다 (MVS는 Alembic 없이 create_all)."""
    Base.metadata.create_all(engine)


# -- ORM 모델 ------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)            # 이름의 슬러그
    display_name = Column(String, nullable=False)
    balance = Column(Float, nullable=False, default=0.0)


class WikiPage(Base):
    __tablename__ = "pages"
    slug = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False, default="")
    summary = Column(Text, nullable=False, default="")
    author_id = Column(String, ForeignKey("users.id"), nullable=False)
    shared = Column(Boolean, nullable=False, default=False)
    links_json = Column(Text, nullable=False, default="[]")
    entities_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    @property
    def links(self) -> list[str]:
        return json.loads(self.links_json or "[]")

    @links.setter
    def links(self, value: list[str]) -> None:
        self.links_json = json.dumps(list(value))

    @property
    def entities(self) -> list[str]:
        return json.loads(self.entities_json or "[]")

    @entities.setter
    def entities(self, value: list[str]) -> None:
        self.entities_json = json.dumps(list(value))


class Stake(Base):
    """한 사용자가 한 페이지에 잠근 포인트 + 인증 투자로 받은 누적 수익."""

    __tablename__ = "stakes"
    __table_args__ = (UniqueConstraint("user_id", "page_slug", name="uq_stake"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    page_slug = Column(String, ForeignKey("pages.slug"), nullable=False)
    amount = Column(Float, nullable=False, default=0.0)     # 현재 잠긴 포인트
    earned = Column(Float, nullable=False, default=0.0)     # 선행 투자자로 받은 누적 수익
    order_idx = Column(Integer, nullable=False)             # 페이지 내 최초 투자 순서(0-base)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MeasurementRow(Base):
    """페이지에 기록된 외부 현실 측정 (인증 닻)."""

    __tablename__ = "measurements"
    id = Column(Integer, primary_key=True, autoincrement=True)
    page_slug = Column(String, ForeignKey("pages.slug"), nullable=False)
    metric = Column(String, nullable=False)
    baseline = Column(Float, nullable=False)
    observed = Column(Float, nullable=False)
    direction = Column(String, nullable=False, default="higher_better")
    min_rel_improvement = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
