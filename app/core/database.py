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
