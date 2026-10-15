from datetime import datetime, timezone


class ContentService:

    def __init__(self, db):
        self.db = db

    async def save_generated_post(
        self,
        user_id: str,
        business_id: str,
        payload: dict,
    ):

        document = {
            "user_id": user_id,
            "business_id": business_id,

            "type": "social_post",

            "product_id": payload.get("product_id"),

            "platform": payload.get("platform"),
            "objective": payload.get("objective"),

            "headline": payload.get("headline"),
            "caption": payload.get("caption"),
            "call_to_action": payload.get("call_to_action"),

            "hashtags": payload.get("hashtags", []),

            "creative_direction": payload.get(
                "creative_direction"
            ),
            "image_url": payload.get("image_url") or payload.get("media_url"),
            "media_url": payload.get("media_url") or payload.get("image_url"),

            "status": "draft",

            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        result = await self.db.contents.insert_one(document)

        document["_id"] = str(result.inserted_id)

        return document