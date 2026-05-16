from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import JSON, MetaData, String, create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    metadata = metadata


session_factory = sessionmaker(autoflush=False, autocommit=False, future=True)


def make_engine(database_url: str) -> Engine:
    return create_engine(database_url, future=True)


def get_session(database_url: str) -> Generator[Session, None, None]:
    engine = make_engine(database_url)
    with session_factory(bind=engine) as session:
        yield session


def json_type() -> JSON:
    return JSON().with_variant(postgresql.JSONB(astext_type=String()), "postgresql")


def inet_type() -> String:
    return String(length=45).with_variant(postgresql.INET(), "postgresql")
