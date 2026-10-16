try:
    import dns.resolver
    resolver = dns.resolver.Resolver(configure=True)
    existing_ns = list(resolver.nameservers)
    for ns in ['8.8.8.8', '1.1.1.1', '8.8.4.4']:
        if ns not in existing_ns:
            existing_ns.append(ns)
    resolver.nameservers = existing_ns
    dns.resolver.default_resolver = resolver
except Exception:
    try:
        import dns.resolver
        dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
        dns.resolver.default_resolver.nameservers = ['8.8.8.8', '1.1.1.1']
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
        print("Closed MongoDB connection.")

def get_database() -> AsyncIOMotorDatabase:
    return db_manager.db
