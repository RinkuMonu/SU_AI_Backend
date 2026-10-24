"""
Role Migration Script for DhandaGrow AI:
Migrates legacy roles to the strict 2-role architecture:
- 'businessman', 'merchant' -> 'business'
- 'user_creator', 'creator' -> 'influencer'

Records all migrated records to role_migration_audit collection for data safety.
"""

import asyncio
from datetime import datetime, timezone
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.database import get_database, close_mongo_connection


async def run_migration():
    db = get_database()
    print("Connected to MongoDB for role migration.")

    collections = ["users", "pending_users"]
    total_migrated = 0

    for col_name in collections:
        col = db[col_name]
        
        # 1. Migrate creator / user_creator -> influencer
        creator_cursor = col.find({"role": {"$in": ["creator", "user_creator"]}})
        async for doc in creator_cursor:
            old_role = doc.get("role")
            await col.update_one(
                {"_id": doc["_id"]},
                {"$set": {"role": "influencer", "accountType": "influencer", "updated_at": datetime.now(timezone.utc)}}
            )
            await db["role_migration_audit"].insert_one({
                "collection": col_name,
                "user_id": str(doc["_id"]),
                "old_role": old_role,
                "new_role": "influencer",
                "migrated_at": datetime.now(timezone.utc)
            })
            total_migrated += 1
            print(f"[{col_name}] Migrated user {doc['_id']} from '{old_role}' to 'influencer'")

        # 2. Migrate businessman / merchant -> business
        biz_cursor = col.find({"role": {"$in": ["businessman", "merchant"]}})
        async for doc in biz_cursor:
            old_role = doc.get("role")
            await col.update_one(
                {"_id": doc["_id"]},
                {"$set": {"role": "business", "accountType": "business", "updated_at": datetime.now(timezone.utc)}}
            )
            await db["role_migration_audit"].insert_one({
                "collection": col_name,
                "user_id": str(doc["_id"]),
                "old_role": old_role,
                "new_role": "business",
                "migrated_at": datetime.now(timezone.utc)
            })
            total_migrated += 1
            print(f"[{col_name}] Migrated user {doc['_id']} from '{old_role}' to 'business'")

    print(f"Role migration completed successfully. Total accounts migrated: {total_migrated}")
    close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(run_migration())
