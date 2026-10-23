import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_get_ai_context_no_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/ai/context")
    # Assuming the current security setup requires auth, this should fail.
    # We expect 401 Unauthorized since we didn't pass a token.
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_generate_caption_no_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/ai/caption", json={
            "product_id": "test_id",
            "objective": "sale",
            "tone": "premium",
            "language": "english",
            "offer": "10% off",
            "cta": "Buy now"
        })
    assert response.status_code == 401
    
@pytest.mark.asyncio
async def test_get_generations_no_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/ai/generations")
    assert response.status_code == 401

# Additional tests would require mocking the database and auth token.
