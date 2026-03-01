"""Deferred API — Test fixtures and configuration."""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio

# Override database URL to SQLite for tests BEFORE any app imports
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["DATABASE_URL_SYNC"] = "sqlite://"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["RABBITMQ_URL"] = "amqp://guest:guest@localhost:5672/"
os.environ["JWT_SECRET_KEY"] = "test_secret_key_for_testing_only_do_not_use"
os.environ["API_DEBUG"] = "false"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    """Create tables before each test, drop after."""
    from app.db import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    """Yield an authenticated test HTTP client."""
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        # Get auth token
        response = await ac.post(
            "/auth/token",
            json={"customer_id": "test_customer", "secret": "test_secret"},
        )
        if response.status_code == 200:
            token = response.json()["access_token"]
            ac.headers["Authorization"] = f"Bearer {token}"
        yield ac


@pytest_asyncio.fixture
async def unauth_client():
    """Yield an unauthenticated test HTTP client."""
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
