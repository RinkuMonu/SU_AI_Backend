from datetime import datetime, timezone
from bson import ObjectId


class ContentService:

    def __init__(self, db):
        self.db = db

    async def save_generated_post(
        self,
        user_id: str,
        business_id: str,
        payload: dict,
    ):
        now = datetime.now(timezone.utc)
        content_type = payload.get("content_type") or "social_post"

        document = {
            "user_id": user_id,
            "business_id": business_id,
            "type": content_type,
            "content_type": content_type,
            "product_id": payload.get("product_id"),
            "product_ids": payload.get("product_ids", []),
            "product_details": payload.get("product_details"),
            "platform": payload.get("platform", "instagram"),
            "objective": payload.get("objective", "product_promotion"),
            "headline": payload.get("headline"),
            "caption": payload.get("caption"),
            "primary_text": payload.get("primary_text"),
            "description": payload.get("description"),
            "call_to_action": payload.get("call_to_action"),
            "hashtags": payload.get("hashtags", []),
            "creative_direction": payload.get("creative_direction"),
            "image_url": payload.get("image_url") or payload.get("media_url"),
            "media_url": payload.get("media_url") or payload.get("image_url"),
            "use_brand_kit": payload.get("use_brand_kit", False),
            "brand_kit_applied": payload.get("brand_kit_applied", False),
            "brand_details": payload.get("brand_details"),
            "status": "draft",
            "created_at": now,
            "updated_at": now,
        }

        result = await self.db.contents.insert_one(document)
        document["_id"] = str(result.inserted_id)

        # Also preserve generation record in ai_generations collection for unified AI history
        try:
            ai_history_doc = {
                "user_id": user_id,
                "business_id": business_id,
                "generation_type": content_type,
                "provider": "gemini",
                "model_name": "gemini-flash-lite-latest",
                "input_params": {
                    "product_id": payload.get("product_id"),
                    "product_ids": payload.get("product_ids"),
                    "platform": payload.get("platform"),
                    "objective": payload.get("objective"),
                    "use_brand_kit": payload.get("use_brand_kit", False),
                },
                "output_data": {
                    "headline": payload.get("headline"),
                    "caption": payload.get("caption"),
                    "image_url": document["image_url"],
                    "hashtags": payload.get("hashtags", []),
                },
                "status": "success",
                "created_at": now,
            }
            await self.db.ai_generations.insert_one(ai_history_doc)
        except Exception:
            pass

        return document

    async def get_content_by_id(self, content_id: str, business_id: str):
        if not ObjectId.is_valid(content_id):
            return None
        doc = await self.db.contents.find_one({
            "_id": ObjectId(content_id),
            "business_id": business_id
        })
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc