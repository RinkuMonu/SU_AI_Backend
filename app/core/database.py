try:
    import dns.resolver
    resolver = dns.resolver.Resolver(configure=True)
    for ns in ['8.8.8.8', '1.1.1.1']:
        if ns not in resolver.nameservers:
            resolver.nameservers.append(ns)
    dns.resolver.default_resolver = resolver
except Exception:
    pass

import asyncio
from typing import Any
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings

class Database:
    client: AsyncIOMotorClient = None
    db: AsyncIOMotorDatabase = None
    loop: Any = None

db_manager = Database()

def connect_to_mongo():
    try:
        db_manager.loop = asyncio.get_running_loop()
    except RuntimeError:
        db_manager.loop = None
    db_manager.client = AsyncIOMotorClient(settings.MONGO_URI)
    db_manager.db = db_manager.client[settings.DATABASE_NAME]
    print("Connected to MongoDB.")

async def init_db_indexes():
    """Create essential unique and lookup indexes across core collections safely."""
    db = get_database()

    async def _safe_create_index(col, *args, **kwargs):
        try:
            await db[col].create_index(*args, **kwargs)
        except Exception:
            pass

    # 1. Users collection: unique sparse index on phone_number and email
    await _safe_create_index(
        "users", "phone_number",
        unique=True,
        partialFilterExpression={"phone_number": {"$type": "string"}},
        background=True
    )
    await _safe_create_index(
        "users", "email",
        unique=True,
        partialFilterExpression={"email": {"$type": "string"}},
        background=True
    )

    # 2. Businesses collection: indexes on owner_id and ownerId
    await _safe_create_index("businesses", "owner_id", background=True)
    await _safe_create_index("businesses", "ownerId", background=True)
    await _safe_create_index("businesses", "user_id", background=True)

    # 3. Brand Kits collection: index on owner_id, business_id, user_id
    await _safe_create_index("brand_kits", "owner_id", background=True)
    await _safe_create_index("brand_kits", "business_id", background=True)
    await _safe_create_index("brand_kits", "user_id", background=True)

    # 4. Subscriptions collection: index on user_id
    await _safe_create_index("subscriptions", "user_id", background=True)

    # 5. Contents collection: index on user_id, business_id
    await _safe_create_index("contents", "user_id", background=True)
    await _safe_create_index("contents", "business_id", background=True)

    # 6. Social connections
    for col_name in ["instagram_connections", "facebook_connections", "linkedin_connections"]:
        await _safe_create_index(col_name, "user_id", background=True)

    # 7. OTP collection
    await _safe_create_index("otps", "expires_at", expireAfterSeconds=0, background=True)
    await _safe_create_index("otps", "phone_number", sparse=True, background=True)

    # 8. Leads collection
    await _safe_create_index("leads", [("created_at", -1)], background=True)
    await _safe_create_index("leads", "email", background=True)
    await _safe_create_index("leads", "status", background=True)

    # 9. Payment transactions collection
    await _safe_create_index("payment_transactions", "transaction_id", unique=True, sparse=True, background=True)
    await _safe_create_index("payment_transactions", "order_id", background=True)
    await _safe_create_index("payment_transactions", "user_id", background=True)
    await _safe_create_index("payment_transactions", [("user_id", 1), ("created_at", -1)], background=True)
    await _safe_create_index("payment_transactions", "status", background=True)
    await _safe_create_index("payment_transactions", "payment_mode", background=True)
    await _safe_create_index("payment_transactions", "created_at", background=True)

    # 10. Product Photoshoot Studio collections
    await _safe_create_index("photoshoot_sessions", "session_id", unique=True, background=True)
    await _safe_create_index("photoshoot_sessions", [("user_id", 1), ("created_at", -1)], background=True)
    await _safe_create_index("photoshoot_images", "image_id", unique=True, background=True)
    await _safe_create_index("photoshoot_images", [("session_id", 1), ("user_id", 1)], background=True)
    await _safe_create_index("photoshoot_jobs", "job_id", unique=True, background=True)
    await _safe_create_index("photoshoot_jobs", "session_id", background=True)
    await _safe_create_index("photoshoot_jobs", "user_id", background=True)

def close_mongo_connection():
    if db_manager.client:
        db_manager.client.close()
        db_manager.client = None
        db_manager.db = None
        print("Closed MongoDB connection.")

def get_database() -> AsyncIOMotorDatabase:
    try:
        current_loop = asyncio.get_running_loop()
        if db_manager.loop is not None and db_manager.loop != current_loop:
            connect_to_mongo()
    except RuntimeError:
        pass
    if db_manager.db is None or db_manager.client is None:
        connect_to_mongo()
    return db_manager.db
