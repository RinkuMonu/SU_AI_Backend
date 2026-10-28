try:
    import dns.resolver
    resolver = dns.resolver.Resolver(configure=True)
    for ns in ['8.8.8.8', '1.1.1.1']:
        if ns not in resolver.nameservers:
            resolver.nameservers.append(ns)
    dns.resolver.default_resolver = resolver
except Exception:
    pass

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings

class Database:
    client: AsyncIOMotorClient = None
    db: AsyncIOMotorDatabase = None

db_manager = Database()

def connect_to_mongo():
    db_manager.client = AsyncIOMotorClient(settings.MONGO_URI)
    db_manager.db = db_manager.client[settings.DATABASE_NAME]
    print("Connected to MongoDB.")

async def init_db_indexes():
    """Create essential unique and lookup indexes across core collections safely."""
    try:
        db = get_database()
        # 1. Users collection: unique sparse index on phone_number and email
        await db["users"].create_index(
            "phone_number",
            unique=True,
            partialFilterExpression={"phone_number": {"$type": "string"}},
            background=True
        )
        await db["users"].create_index(
            "email",
            unique=True,
            partialFilterExpression={"email": {"$type": "string"}},
            background=True
        )

        # 2. Businesses collection: indexes on owner_id and ownerId
        await db["businesses"].create_index("owner_id", background=True)
        await db["businesses"].create_index("ownerId", background=True)
        await db["businesses"].create_index("user_id", background=True)

        # 3. Brand Kits collection: index on owner_id, business_id, user_id
        await db["brand_kits"].create_index("owner_id", background=True)
        await db["brand_kits"].create_index("business_id", background=True)
        await db["brand_kits"].create_index("user_id", background=True)

        # 4. Subscriptions collection: index on user_id
        await db["subscriptions"].create_index("user_id", background=True)

        # 5. Contents collection: index on user_id, business_id
        await db["contents"].create_index("user_id", background=True)
        await db["contents"].create_index("business_id", background=True)

        # 6. Social connections
        for col_name in ["instagram_connections", "facebook_connections", "linkedin_connections"]:
            await db[col_name].create_index("user_id", background=True)

        # 7. OTP collection
        await db["otps"].create_index("expires_at", expireAfterSeconds=0, background=True)
        await db["otps"].create_index("phone_number", sparse=True, background=True)
    except Exception as e:
        print(f"Warning: Non-fatal error initializing MongoDB indexes: {e}")

def close_mongo_connection():
    if db_manager.client:
        db_manager.client.close()
        db_manager.client = None
        db_manager.db = None
        print("Closed MongoDB connection.")

def get_database() -> AsyncIOMotorDatabase:
    if db_manager.db is None or db_manager.client is None:
        connect_to_mongo()
    return db_manager.db
