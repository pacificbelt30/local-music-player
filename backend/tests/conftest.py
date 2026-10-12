import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as app_database
from app.database import Base, get_db
from app.main import app
from app.tasks.celery_app import celery_app

# Unit tests must not wait for a real broker or Redis result backend.
celery_app.conf.update(broker_url="memory://", result_backend="cache+memory://")

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch, tmp_path):
    # Existing adapter unit tests mock YoutubeDL in-process. Process integration
    # tests explicitly remove this flag to exercise the production boundary.
    monkeypatch.setenv("YTDLP_CHILD", "1")
    monkeypatch.setattr("app.config.settings.data_path", tmp_path)

# StaticPool forces all sessions to share one connection so in-memory tables
# are visible across sessions and threads.
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(autouse=True)
def patch_session_local():
    # Endpoints that bypass get_db (health, rescan) import SessionLocal directly;
    # patching the module attribute intercepts those runtime imports.
    with patch.object(app_database, "SessionLocal", TestSessionLocal):
        yield


@pytest.fixture
def db():
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
