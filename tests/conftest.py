from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db import create_db_engine  # noqa: E402


@pytest.fixture(scope="session")
def database_url(tmp_path_factory):
    configured = os.environ.get("TEST_DATABASE_URL")
    if configured:
        engine = create_engine(configured, future=True)
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        engine.dispose()
        return configured
    path = tmp_path_factory.mktemp("review_events") / "test.db"
    return "sqlite:///" + str(path)


@pytest.fixture(scope="session")
def alembic_config(database_url):
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    os.environ["REVIEW_EVENT_DB_URL"] = database_url
    return config


@pytest.fixture()
def engine(alembic_config, database_url):
    command.upgrade(alembic_config, "head")
    engine = (
        create_db_engine(database_url)
        if database_url.startswith("sqlite")
        else create_engine(database_url, future=True)
    )
    try:
        yield engine
    finally:
        command.downgrade(alembic_config, "base")
        engine.dispose()


@pytest.fixture()
def session(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
