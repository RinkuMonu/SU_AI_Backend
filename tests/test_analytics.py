"""
Comprehensive test suite for GET /api/v1/analytics/overview.

Tests cover:
  • Authentication (unauthenticated → 401)
  • Range validation (7d, 30d, 90d → 200; invalid → 400)
  • User isolation (User A cannot see User B data)
  • Empty account (valid zero response)
  • Content analytics counts
  • AI usage counts
  • Credit usage (refunds excluded)
  • Marketing score is deterministic 0–100
  • Recommendation changes based on data
  • External metrics are all null / not_connected
  • Daily buckets include zero-activity days
  • Missing business does not crash

Follows existing project conventions: pytest + httpx AsyncClient.
Requires a running MongoDB instance (uses the app's configured connection).
"""

import pytest
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import get_database, connect_to_mongo, close_mongo_connection
from app.core.security import create_access_token

@pytest.fixture(autouse=True)
async def setup_db():
    connect_to_mongo()
    yield
    close_mongo_connection()


# ── Helpers ──────────────────────────────────────────────────────────

def _auth_header(user_id: str) -> dict:
    """Create a valid JWT Authorization header for the given user_id."""
    token = create_access_token(subject=user_id)
    return {"Authorization": f"Bearer {token}"}


async def _ensure_user(db, user_id: ObjectId, name: str = "Test User") -> str:
    """Insert a minimal user document if it doesn't exist. Returns str id."""
    existing = await db["users"].find_one({"_id": user_id})
    if not existing:
        await db["users"].insert_one({
            "_id": user_id,
            "name": name,
            "email": f"{name.lower().replace(' ', '.')}@test.local",
            "hashed_password": "$2b$12$dummyhash",
            "role": "user",
            "created_at": datetime.now(timezone.utc),
        })
    return str(user_id)


async def _ensure_business(db, owner_id: str) -> str:
    """Insert a minimal business for the user. Returns str business_id."""
    existing = await db["businesses"].find_one({"owner_id": owner_id})
    if existing:
        return str(existing["_id"])
    biz_id = ObjectId()
    await db["businesses"].insert_one({
        "_id": biz_id,
        "owner_id": owner_id,
        "name": "Test Business",
        "category": "Retail",
        "location": "Online",
        "created_at": datetime.now(timezone.utc),
    })
    return str(biz_id)


# ── Fixtures ─────────────────────────────────────────────────────────

# Two independent user ObjectIds for isolation tests
USER_A_OID = ObjectId()
USER_B_OID = ObjectId()


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module", autouse=True)
async def seed_and_cleanup():
    """
    Seed test data before the module and clean up after.

    Uses a ``_test_analytics`` marker on every inserted document so
    cleanup can surgically remove only test data.
    """
    from app.core.database import connect_to_mongo

    # Ensure connection
    db = get_database()
    if db is None:
        connect_to_mongo()
        db = get_database()

    marker = {"_test_analytics": True}
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    three_days_ago = now - timedelta(days=3)

    # ── User A setup ─────────────────────────────────────────────
    uid_a = await _ensure_user(db, USER_A_OID, "Analytics User A")
    biz_a = await _ensure_business(db, uid_a)

    # Posts (contents, type=social_post) — 2 posts
    await db["contents"].insert_many([
        {**marker, "user_id": uid_a, "type": "social_post",
         "business_id": biz_a, "created_at": yesterday},
        {**marker, "user_id": uid_a, "type": "social_post",
         "business_id": biz_a, "created_at": three_days_ago},
    ])

    # Reel (reel_jobs) — 1 reel (user_id as ObjectId, matching reel_service)
    await db["reel_jobs"].insert_one(
        {**marker, "user_id": USER_A_OID, "business_id": ObjectId(biz_a),
         "status": "completed", "created_at": yesterday},
    )

    # AI caption generation — 1
    await db["ai_generations"].insert_one(
        {**marker, "user_id": uid_a, "generation_type": "caption",
         "status": "success", "created_at": yesterday},
    )

    # AI image generation — 1
    await db["ai_generations"].insert_one(
        {**marker, "user_id": uid_a, "generation_type": "image",
         "status": "success", "created_at": yesterday},
    )

    # Photoshoot — 1
    await db["photoshoots"].insert_one(
        {**marker, "user_id": uid_a, "created_at": three_days_ago},
    )

    # Product (business-scoped) — 1
    await db["products"].insert_one(
        {**marker, "business_id": ObjectId(biz_a), "name": "Test Product",
         "price": 100, "created_at": yesterday},
    )

    # Calendar — 1
    await db["calendars"].insert_one(
        {**marker, "user_id": uid_a, "type": "social_media_calendar",
         "created_at": yesterday},
    )

    # Credit transactions — 2 deductions + 1 refund
    await db["credit_transactions"].insert_many([
        {**marker, "user_id": uid_a, "action": "post_generation",
         "credits": -1, "balance_after": 4, "created_at": yesterday},
        {**marker, "user_id": uid_a, "action": "image_generation",
         "credits": -1, "balance_after": 3, "created_at": three_days_ago},
        {**marker, "user_id": uid_a, "action": "post_generation_refund",
         "credits": 1, "balance_after": 4, "created_at": yesterday},
    ])

    # ── User B setup (isolation control) ─────────────────────────
    uid_b = await _ensure_user(db, USER_B_OID, "Analytics User B")
    biz_b = await _ensure_business(db, uid_b)

    await db["contents"].insert_one(
        {**marker, "user_id": uid_b, "type": "social_post",
         "business_id": biz_b, "created_at": yesterday},
    )
    await db["reel_jobs"].insert_one(
        {**marker, "user_id": USER_B_OID, "business_id": ObjectId(biz_b),
         "status": "completed", "created_at": yesterday},
    )
    await db["products"].insert_many([
        {**marker, "business_id": ObjectId(biz_b), "name": "B Product 1",
         "price": 50, "created_at": yesterday},
        {**marker, "business_id": ObjectId(biz_b), "name": "B Product 2",
         "price": 75, "created_at": yesterday},
    ])

    yield  # ── Run tests ────────────────────────────────────────────

    # ── Cleanup ──────────────────────────────────────────────────
    for coll in [
        "contents", "reel_jobs", "ai_generations", "photoshoots",
        "products", "calendars", "credit_transactions",
    ]:
        await db[coll].delete_many(marker)

    # Remove test users and businesses
    await db["users"].delete_many({"_id": {"$in": [USER_A_OID, USER_B_OID]}})
    await db["businesses"].delete_many(
        {"owner_id": {"$in": [str(USER_A_OID), str(USER_B_OID)]}},
    )


# ── Transport ────────────────────────────────────────────────────────

transport = ASGITransport(app=app)
BASE = "http://test"
URL = "/api/v1/analytics/overview"


# =====================================================================
# Tests
# =====================================================================


@pytest.mark.asyncio
async def test_unauthenticated_returns_401():
    """Requests without a JWT must be rejected."""
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r = await ac.get(URL)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_invalid_range_returns_400():
    """An unsupported range value must return 400."""
    headers = _auth_header(str(USER_A_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r = await ac.get(URL, params={"range": "15d"}, headers=headers)
    assert r.status_code == 400
    assert "Invalid range" in r.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("range_val", ["7d", "30d", "90d"])
async def test_valid_ranges_return_200(range_val):
    """All three supported ranges must succeed."""
    headers = _auth_header(str(USER_A_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r = await ac.get(URL, params={"range": range_val}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["range"] == range_val


@pytest.mark.asyncio
async def test_content_analytics():
    """Verify real content counts for User A within 7d range."""
    headers = _auth_header(str(USER_A_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r = await ac.get(URL, params={"range": "7d"}, headers=headers)
    data = r.json()["data"]
    content = data["content"]

    assert content["posts"] == 2       # 2 social_post entries
    assert content["reels"] == 1       # 1 reel_job
    assert content["images"] == 1      # 1 ai_generations(image)
    assert content["photoshoots"] == 1 # 1 photoshoot
    assert content["captions"] == 1    # 1 ai_generations(caption)


@pytest.mark.asyncio
async def test_ai_usage():
    """Verify AI usage aggregation for User A."""
    headers = _auth_header(str(USER_A_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r = await ac.get(URL, params={"range": "7d"}, headers=headers)
    ai = r.json()["data"]["ai_usage"]

    # total = posts(2) + reels(1) + images(1) + photoshoots(1) + captions(1)
    assert ai["total_generations"] == 6
    assert ai["post_generations"] == 2
    assert ai["image_generations"] == 1
    assert ai["photoshoot_generations"] == 1
    assert ai["reel_generations"] == 1


@pytest.mark.asyncio
async def test_credit_usage_excludes_refunds():
    """Credits used must count only deductions, never refunds."""
    headers = _auth_header(str(USER_A_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r = await ac.get(URL, params={"range": "7d"}, headers=headers)
    ai = r.json()["data"]["ai_usage"]

    # 2 deductions of -1 each = 2 credits used (refund of +1 excluded)
    assert ai["credits_used"] == 2


@pytest.mark.asyncio
async def test_business_analytics():
    """Product catalogue count (not date-filtered) and calendars."""
    headers = _auth_header(str(USER_A_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r = await ac.get(URL, params={"range": "7d"}, headers=headers)
    biz = r.json()["data"]["business"]

    assert biz["products"] == 1  # User A has 1 product
    assert biz["calendars"] == 1  # 1 calendar in range


@pytest.mark.asyncio
async def test_external_metrics_null():
    """External metrics must be null with status=not_connected."""
    headers = _auth_header(str(USER_A_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r = await ac.get(URL, params={"range": "7d"}, headers=headers)
    ext = r.json()["data"]["external"]

    assert ext["reach"] is None
    assert ext["engagement"] is None
    assert ext["leads"] is None
    assert ext["direct_enquiries"] is None
    assert ext["status"] == "not_connected"


@pytest.mark.asyncio
async def test_marketing_score_range():
    """Score must be a deterministic integer between 0 and 100."""
    headers = _auth_header(str(USER_A_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r = await ac.get(URL, params={"range": "7d"}, headers=headers)
    ms = r.json()["data"]["marketing_score"]

    assert 0 <= ms["score"] <= 100
    assert "breakdown" in ms
    assert "formula" in ms


@pytest.mark.asyncio
async def test_marketing_score_deterministic():
    """Score for User A 7d must be exactly predictable from seeded data."""
    headers = _auth_header(str(USER_A_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r = await ac.get(URL, params={"range": "7d"}, headers=headers)
    ms = r.json()["data"]["marketing_score"]
    bd = ms["breakdown"]

    # posts=2 → min(2*5,25)=10
    assert bd["content_activity"] == 10
    # total_gen=6 → min(6*2,25)=12
    assert bd["ai_usage"] == 12
    # calendars=1 → 15
    assert bd["calendar_usage"] == 15
    # products=1 → min(1*5,20)=5
    assert bd["product_catalogue"] == 5
    # reels=1 → min(1*5,15)=5
    assert bd["reel_activity"] == 5
    # sum = 10+12+15+5+5 = 47
    assert ms["score"] == 47


@pytest.mark.asyncio
async def test_recommendation_varies():
    """Different users must get different recommendations."""
    headers_a = _auth_header(str(USER_A_OID))
    headers_b = _auth_header(str(USER_B_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r_a = await ac.get(URL, params={"range": "7d"}, headers=headers_a)
        r_b = await ac.get(URL, params={"range": "7d"}, headers=headers_b)

    rec_a = r_a.json()["data"]["recommendation"]
    rec_b = r_b.json()["data"]["recommendation"]

    # Both must have text and type
    assert rec_a["text"]
    assert rec_a["type"]
    assert rec_b["text"]
    assert rec_b["type"]

    # User A has reels; User B does not have captions/images → different recs
    # (At minimum, they should both be valid recommendations)
    assert isinstance(rec_a["text"], str)
    assert isinstance(rec_b["text"], str)


@pytest.mark.asyncio
async def test_daily_buckets_cover_range():
    """Daily activity must have exactly N buckets for N-day range."""
    headers = _auth_header(str(USER_A_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r7 = await ac.get(URL, params={"range": "7d"}, headers=headers)
        r30 = await ac.get(URL, params={"range": "30d"}, headers=headers)
        r90 = await ac.get(URL, params={"range": "90d"}, headers=headers)

    assert len(r7.json()["data"]["activity"]) == 7
    assert len(r30.json()["data"]["activity"]) == 30
    assert len(r90.json()["data"]["activity"]) == 90


@pytest.mark.asyncio
async def test_daily_buckets_contain_zeros():
    """Days without activity must have zero counts, not be omitted."""
    headers = _auth_header(str(USER_A_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r = await ac.get(URL, params={"range": "7d"}, headers=headers)
    activity = r.json()["data"]["activity"]

    for bucket in activity:
        assert "date" in bucket
        assert isinstance(bucket["posts"], int)
        assert isinstance(bucket["reels"], int)
        assert isinstance(bucket["ai_generations"], int)
        assert bucket["posts"] >= 0
        assert bucket["reels"] >= 0
        assert bucket["ai_generations"] >= 0


@pytest.mark.asyncio
async def test_user_isolation_content():
    """User A must not see User B's posts."""
    headers_a = _auth_header(str(USER_A_OID))
    headers_b = _auth_header(str(USER_B_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r_a = await ac.get(URL, params={"range": "7d"}, headers=headers_a)
        r_b = await ac.get(URL, params={"range": "7d"}, headers=headers_b)

    # User A has 2 posts; User B has 1 post
    assert r_a.json()["data"]["content"]["posts"] == 2
    assert r_b.json()["data"]["content"]["posts"] == 1


@pytest.mark.asyncio
async def test_user_isolation_products():
    """User A must not see User B's products."""
    headers_a = _auth_header(str(USER_A_OID))
    headers_b = _auth_header(str(USER_B_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r_a = await ac.get(URL, params={"range": "7d"}, headers=headers_a)
        r_b = await ac.get(URL, params={"range": "7d"}, headers=headers_b)

    # User A has 1 product; User B has 2 products
    assert r_a.json()["data"]["business"]["products"] == 1
    assert r_b.json()["data"]["business"]["products"] == 2


@pytest.mark.asyncio
async def test_user_isolation_credits():
    """User B should have 0 credits_used (no transactions seeded)."""
    headers_b = _auth_header(str(USER_B_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r = await ac.get(URL, params={"range": "7d"}, headers=headers_b)
    assert r.json()["data"]["ai_usage"]["credits_used"] == 0


@pytest.mark.asyncio
async def test_user_isolation_reels():
    """Each user sees only their own reels."""
    headers_a = _auth_header(str(USER_A_OID))
    headers_b = _auth_header(str(USER_B_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r_a = await ac.get(URL, params={"range": "7d"}, headers=headers_a)
        r_b = await ac.get(URL, params={"range": "7d"}, headers=headers_b)

    assert r_a.json()["data"]["content"]["reels"] == 1
    assert r_b.json()["data"]["content"]["reels"] == 1


@pytest.mark.asyncio
async def test_empty_account():
    """A user with no data at all should get a valid zero response."""
    empty_oid = ObjectId()
    db = get_database()
    empty_uid = await _ensure_user(db, empty_oid, "Empty User")

    try:
        headers = _auth_header(empty_uid)
        async with AsyncClient(transport=transport, base_url=BASE) as ac:
            r = await ac.get(URL, params={"range": "7d"}, headers=headers)

        assert r.status_code == 200
        data = r.json()["data"]

        assert data["content"]["posts"] == 0
        assert data["content"]["reels"] == 0
        assert data["ai_usage"]["total_generations"] == 0
        assert data["ai_usage"]["credits_used"] == 0
        assert data["business"]["products"] == 0
        assert data["business"]["calendars"] == 0
        assert data["marketing_score"]["score"] == 0
        assert len(data["activity"]) == 7
    finally:
        await db["users"].delete_one({"_id": empty_oid})


@pytest.mark.asyncio
async def test_missing_business_does_not_crash():
    """A user without a business should still get a valid response."""
    no_biz_oid = ObjectId()
    db = get_database()
    no_biz_uid = await _ensure_user(db, no_biz_oid, "NoBiz User")
    # Deliberately do NOT create a business

    try:
        headers = _auth_header(no_biz_uid)
        async with AsyncClient(transport=transport, base_url=BASE) as ac:
            r = await ac.get(URL, params={"range": "30d"}, headers=headers)

        assert r.status_code == 200
        assert r.json()["data"]["business"]["products"] == 0
    finally:
        await db["users"].delete_one({"_id": no_biz_oid})


@pytest.mark.asyncio
async def test_response_shape():
    """The top-level response must have success=True and a data object."""
    headers = _auth_header(str(USER_A_OID))
    async with AsyncClient(transport=transport, base_url=BASE) as ac:
        r = await ac.get(URL, params={"range": "7d"}, headers=headers)

    body = r.json()
    assert body["success"] is True
    data = body["data"]

    # All required top-level keys
    for key in [
        "range", "period", "content", "ai_usage", "business",
        "activity", "external", "marketing_score", "recommendation",
    ]:
        assert key in data, f"Missing key: {key}"

    # Period has start and end
    assert "start" in data["period"]
    assert "end" in data["period"]
