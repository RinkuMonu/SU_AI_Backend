from app.core.database import get_database
from typing import Dict, Any, List

class AdminDashboardService:
    @staticmethod
    async def get_total_users() -> int:
        db = get_database()
        # Count non-admin platform users
        return await db["users"].count_documents({"role": {"$ne": "admin"}})

    @staticmethod
    async def get_total_businesses() -> int:
        db = get_database()
        return await db["businesses"].count_documents({})

    @staticmethod
    async def get_recent_users(limit: int = 5) -> List[Dict[str, Any]]:
        db = get_database()
        cursor = db["users"].find({"role": {"$ne": "admin"}}).sort("_id", -1).limit(limit)
        users = []
        async for doc in cursor:
            users.append({
                "id": str(doc["_id"]),
                "name": doc.get("name", "Unknown"),
                "email": doc.get("email", ""),
                "role": doc.get("role"),
                "created_at": doc.get("created_at")
            })
        return users


    @staticmethod
    async def get_recent_businesses(limit: int = 5) -> List[Dict[str, Any]]:
        db = get_database()
        cursor = db["businesses"].find({}).sort("_id", -1).limit(limit)
        businesses = []
        async for doc in cursor:
            businesses.append({
                "id": str(doc["_id"]),
                "name": doc.get("name", "Unknown"),
                "owner_id": str(doc.get("owner_id", "")),
                "category": doc.get("category", "Unknown"),
                "location": doc.get("location", "Unknown"),
                "created_at": doc.get("created_at")
            })
        return businesses

    @staticmethod
    async def get_subscription_stats() -> Any:
        # Not implemented in existing schema
        return None

    @staticmethod
    async def get_credit_stats() -> Any:
        # Not implemented in existing schema
        return None

    @staticmethod
    async def get_ai_usage() -> Dict[str, Any]:
        db = get_database()
        collection = db["ai_generations"]
        
        # Aggregate AI usage based on AIGenerationHistory records
        total_generations = await collection.count_documents({})
        posts_generated = await collection.count_documents({"generation_type": "caption"})
        reels_generated = await collection.count_documents({"generation_type": "reel"})
        images_generated = await collection.count_documents({"generation_type": "image"})
        photoshoots_generated = await collection.count_documents({"generation_type": "photoshoot"})

        return {
            "posts_generated": posts_generated,
            "reels_generated": reels_generated,
            "images_generated": images_generated,
            "photoshoots_generated": photoshoots_generated,
            "total_generations": total_generations
        }
