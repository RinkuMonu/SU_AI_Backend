from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from bson import ObjectId
from app.core.database import get_database


class InfluencerOnboardingRepository:
    """
    Dedicated MongoDB repository for progressive Influencer Creator Onboarding.
    Ensures safe partial updates ($set) without wiping previously entered user data.
    """

    @staticmethod
    def _collection():
        db = get_database()
        return db["influencer_profiles"]

    @staticmethod
    def _users_collection():
        db = get_database()
        return db["users"]

    @staticmethod
    def _clean_doc(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Ensure MongoDB documents are JSON-serializable by converting/removing ObjectId."""
        if not doc:
            return doc
        clean = dict(doc)
        if "_id" in clean:
            clean["id"] = str(clean["_id"])
            del clean["_id"]
        return clean

    @classmethod
    async def get_by_user_id(cls, user_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the influencer profile document associated with the authenticated user."""
        col = cls._collection()
        doc = await col.find_one({"user_id": str(user_id)})
        return cls._clean_doc(doc)

    @classmethod
    async def check_username_exists(cls, username: str, exclude_user_id: Optional[str] = None) -> bool:
        """
        Case-insensitive username uniqueness check across influencer_profiles.
        Excludes the profile owned by exclude_user_id if provided.
        """
        col = cls._collection()
        clean_username = username.strip().lstrip("@")
        if not clean_username:
            return False

        query: Dict[str, Any] = {
            "username": {"$regex": f"^{clean_username}$", "$options": "i"}
        }
        if exclude_user_id:
            query["user_id"] = {"$ne": str(exclude_user_id)}

        doc = await col.find_one(query, {"_id": 1})
        return doc is not None

    @classmethod
    async def partial_save(cls, user_id: str, updates: Dict[str, Any], step_number: Optional[int] = None) -> Dict[str, Any]:
        """
        Progressively save onboarding fields using MongoDB $set.
        Omitted fields are left untouched, preserving partial progress across page reloads.
        """
        col = cls._collection()
        now = datetime.now(timezone.utc)

        # Build $set payload excluding protected primary keys
        set_payload: Dict[str, Any] = {
            "updated_at": now
        }

        for key, value in updates.items():
            if key in ["_id", "id", "user_id", "created_at"]:
                continue
            set_payload[key] = value

        # Update step tracking if provided
        if step_number is not None:
            set_payload["current_step"] = step_number

        # Build update operators
        set_on_insert: Dict[str, Any] = {
            "user_id": str(user_id),
            "created_at": now,
            "onboarding_status": "IN_PROGRESS"
        }
        if step_number is None:
            set_on_insert["completed_steps"] = []

        update_ops: Dict[str, Any] = {
            "$set": set_payload,
            "$setOnInsert": set_on_insert
        }

        # If a step is marked complete, push to completed_steps array without duplicates
        if step_number is not None:
            update_ops["$addToSet"] = {"completed_steps": step_number}

        await col.update_one(
            {"user_id": str(user_id)},
            update_ops,
            upsert=True
        )

        # Mirror step progress and creator identity to users collection for consistency
        users_col = cls._users_collection()
        user_obj_id = ObjectId(user_id) if ObjectId.is_valid(user_id) else None
        user_filter = {"_id": user_obj_id} if user_obj_id else {"_id": user_id}
        user_updates: Dict[str, Any] = {
            "updated_at": now
        }
        if step_number is not None:
            user_updates["onboarding_step"] = step_number
            user_updates["onboarding_status"] = "in_progress"
        if "full_name" in updates or "fullName" in updates:
            name_val = updates.get("full_name") or updates.get("fullName")
            user_updates["name"] = name_val
            user_updates["fullName"] = name_val
        if "username" in updates and updates["username"]:
            user_updates["username"] = updates["username"]
        if "profile_image" in updates and updates["profile_image"]:
            user_updates["profileImageUrl"] = updates["profile_image"]
            user_updates["image"] = updates["profile_image"]

        await users_col.update_one(
            user_filter,
            {"$set": user_updates}
        )

        updated = await col.find_one({"user_id": str(user_id)})
        return cls._clean_doc(updated) or {}

    @classmethod
    async def update_progress(cls, user_id: str, current_step: int, completed_steps: Optional[List[int]] = None) -> Dict[str, Any]:
        """Update active step and completed steps array without overwriting form fields."""
        col = cls._collection()
        now = datetime.now(timezone.utc)

        set_payload: Dict[str, Any] = {
            "current_step": current_step,
            "updated_at": now
        }
        if completed_steps is not None:
            set_payload["completed_steps"] = list(set(completed_steps))

        await col.update_one(
            {"user_id": str(user_id)},
            {
                "$set": set_payload,
                "$setOnInsert": {
                    "user_id": str(user_id),
                    "created_at": now,
                    "onboarding_status": "IN_PROGRESS"
                }
            },
            upsert=True
        )

        # Mirror to users collection
        users_col = cls._users_collection()
        user_obj_id = ObjectId(user_id) if ObjectId.is_valid(user_id) else None
        user_filter = {"_id": user_obj_id} if user_obj_id else {"_id": user_id}
        await users_col.update_one(
            user_filter,
            {"$set": {"onboarding_step": current_step, "updated_at": now}}
        )

        updated = await col.find_one({"user_id": str(user_id)})
        return cls._clean_doc(updated) or {}

    @classmethod
    async def finalize_onboarding(cls, user_id: str) -> Dict[str, Any]:
        """
        Atomically mark influencer onboarding COMPLETED in both influencer_profiles and users collections.
        """
        col = cls._collection()
        users_col = cls._users_collection()
        now = datetime.now(timezone.utc)

        # 1. Update influencer_profiles
        await col.update_one(
            {"user_id": str(user_id)},
            {
                "$set": {
                    "onboarding_status": "COMPLETED",
                    "current_step": 7,
                    "updated_at": now,
                    "completed_at": now
                },
                "$addToSet": {"completed_steps": {"$each": [1, 2, 3, 4, 5, 6, 7]}}
            },
            upsert=True
        )

        # 2. Update users document with completion and sync identity fields
        user_obj_id = ObjectId(user_id) if ObjectId.is_valid(user_id) else None
        user_filter = {"_id": user_obj_id} if user_obj_id else {"_id": user_id}
        profile_doc = await col.find_one({"user_id": str(user_id)}) or {}
        name_val = profile_doc.get("full_name") or profile_doc.get("fullName")
        un_val = profile_doc.get("username")
        img_val = profile_doc.get("profile_image") or profile_doc.get("profileImageUrl")

        user_updates: Dict[str, Any] = {
            "role": "influencer",
            "accountType": "personal",
            "onboardingCompleted": True,
            "influencer_onboarding_completed": True,
            "onboarding_status": "completed",
            "onboarding_step": 7,
            "onboarding_completed_at": now,
            "updated_at": now
        }
        if name_val:
            user_updates["name"] = name_val
            user_updates["fullName"] = name_val
        if un_val:
            user_updates["username"] = un_val
        if img_val:
            user_updates["profileImageUrl"] = img_val
            user_updates["image"] = img_val

        await users_col.update_one(
            user_filter,
            {"$set": user_updates}
        )

        final_doc = await col.find_one({"user_id": str(user_id)})
        return cls._clean_doc(final_doc) or {}
