import httpx
from datetime import datetime, timezone
from fastapi import HTTPException
from bson import ObjectId

class SocialService:
    @staticmethod
    async def _find_content_or_reel(db, content_id: str):
        query = {"_id": ObjectId(content_id)} if ObjectId.is_valid(content_id) else {"_id": content_id}
        
        # 1. Search in contents
        item = await db["contents"].find_one(query)
        if not item and ObjectId.is_valid(content_id):
            item = await db["contents"].find_one({"_id": str(content_id)})
            
        # 2. Search in reel_jobs
        if not item:
            item = await db["reel_jobs"].find_one(query)
            if not item and ObjectId.is_valid(content_id):
                item = await db["reel_jobs"].find_one({"_id": str(content_id)})
                
        return item

    @staticmethod
    async def publish_to_instagram(db, business_id: str, content_id: str):
        """
        Unified Instagram publishing via InstagramService.
        Supports both regular content items and AI Reels.
        """
        from app.services.instagram_service import InstagramService

        content = await SocialService._find_content_or_reel(db, content_id)
        if not content:
            raise HTTPException(status_code=404, detail="Content or Reel not found")

        image_url = (
            content.get("thumbnail_url")
            or content.get("image_url")
            or content.get("media_url")
            or content.get("imageUrl")
            or content.get("video_url")
        )

        caption = content.get("caption", "")
        if not caption and content.get("script"):
            script = content.get("script")
            if isinstance(script, dict):
                caption = script.get("caption") or script.get("hook") or ""

        hashtags = content.get("hashtags", "")
        if not hashtags and content.get("script"):
            script = content.get("script")
            if isinstance(script, dict):
                hashtags = script.get("hashtags") or []

        if isinstance(hashtags, list):
            hashtags = " ".join([h if h.startswith("#") else f"#{h}" for h in hashtags])

        full_caption = f"{caption}\n\n{hashtags}".strip() if hashtags else caption.strip()
        if not full_caption and content.get("product_name"):
            full_caption = f"Check out our new {content['product_name']}! 🔥"

        if not image_url:
            image_url = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1080&q=80"

        effective_user_id = str(business_id)
        conn = await InstagramService.get_connection(db, effective_user_id)
        if not conn and content.get("user_id"):
            content_user_id = str(content.get("user_id"))
            conn_content = await InstagramService.get_connection(db, content_user_id)
            if conn_content:
                effective_user_id = content_user_id

        res = await InstagramService.publish_image(
            db=db,
            user_id=effective_user_id,
            image_url=image_url,
            caption=full_caption,
            content_id=content_id,
        )

        now_utc = datetime.now(timezone.utc)
        if ObjectId.is_valid(content_id):
            await db["contents"].update_one(
                {"_id": ObjectId(content_id)},
                {"$set": {"status": "published", "published_at": now_utc, "platform": "instagram"}}
            )
            await db["reel_jobs"].update_one(
                {"_id": ObjectId(content_id)},
                {"$set": {"status": "published", "published_at": now_utc, "platform": "instagram"}}
            )

        return res

    @staticmethod
    async def publish_to_facebook(db, business_id: str, content_id: str):
        from app.services.facebook_service import FacebookService
        
        content = await SocialService._find_content_or_reel(db, content_id)
        if not content:
            raise HTTPException(status_code=404, detail="Content or Reel not found")
            
        image_url = (
            content.get("thumbnail_url")
            or content.get("image_url")
            or content.get("media_url")
            or content.get("imageUrl")
            or content.get("video_url")
        )

        caption = content.get("caption", "")
        if not caption and content.get("script"):
            script = content.get("script")
            if isinstance(script, dict):
                caption = script.get("caption") or script.get("hook") or ""

        hashtags = content.get("hashtags", "")
        if not hashtags and content.get("script"):
            script = content.get("script")
            if isinstance(script, dict):
                hashtags = script.get("hashtags") or []

        if isinstance(hashtags, list):
            hashtags = " ".join([h if h.startswith("#") else f"#{h}" for h in hashtags])

        full_caption = f"{caption}\n\n{hashtags}".strip() if hashtags else caption.strip()
        if not full_caption and content.get("product_name"):
            full_caption = f"Check out our new {content['product_name']}! 🔥"
        
        user_id = content.get("user_id") or business_id
        res = await FacebookService.publish_post(
            db=db,
            user_id=str(user_id),
            caption=full_caption,
            image_url=image_url,
            content_id=content_id,
        )

        now_utc = datetime.now(timezone.utc)
        if ObjectId.is_valid(content_id):
            await db["contents"].update_one(
                {"_id": ObjectId(content_id)},
                {"$set": {"status": "published", "published_at": now_utc, "platform": "facebook"}}
            )
            await db["reel_jobs"].update_one(
                {"_id": ObjectId(content_id)},
                {"$set": {"status": "published", "published_at": now_utc, "platform": "facebook"}}
            )

        return res

    @staticmethod
    async def publish_to_linkedin(db, business_id: str, content_id: str):
        business = await db["businesses"].find_one({"_id": ObjectId(business_id)}) if ObjectId.is_valid(business_id) else await db["businesses"].find_one({"owner_id": str(business_id)})
        if not business:
            business = await db["businesses"].find_one({})

        linkedin_author_id = business.get("linkedin_author_id") if business else None
        linkedin_access_token = business.get("linkedin_access_token") if business else None
        
        # Fallback to users or linkedin_connections
        if not linkedin_author_id or not linkedin_access_token:
            owner_id = (business.get("ownerId") or business.get("owner_id")) if business else business_id
            oid = ObjectId(owner_id) if ObjectId.is_valid(str(owner_id)) else str(owner_id)
            user_doc = await db["users"].find_one({"_id": oid})
            if user_doc:
                linkedin_author_id = linkedin_author_id or user_doc.get("linkedin_author_id")
                linkedin_access_token = linkedin_access_token or user_doc.get("linkedin_access_token")
            
            if not linkedin_author_id or not linkedin_access_token:
                conn = await db["linkedin_connections"].find_one({"connected": True})
                if conn:
                    linkedin_author_id = linkedin_author_id or conn.get("author_id")
                    linkedin_access_token = linkedin_access_token or conn.get("access_token")

        if not linkedin_author_id or not linkedin_access_token:
            raise HTTPException(status_code=400, detail="LinkedIn is not connected. Please connect LinkedIn in Settings > Social Platforms or Login with LinkedIn.")
            
        content = await SocialService._find_content_or_reel(db, content_id)
        if not content:
            raise HTTPException(status_code=404, detail="Content or Reel not found")
            
        image_url = content.get("image_url") or content.get("thumbnail_url")
        caption = content.get("caption", "")
        hashtags = content.get("hashtags", "")
        if isinstance(hashtags, list):
            hashtags = " ".join(hashtags)
        full_caption = f"{caption}\n\n{hashtags}".strip()
        
        url = "https://api.linkedin.com/v2/ugcPosts"
        headers = {
            "Authorization": f"Bearer {linkedin_access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json"
        }
        
        share_content = {
            "shareCommentary": {
                "text": full_caption
            },
            "shareMediaCategory": "NONE"
        }
        
        if image_url:
            share_content["shareMediaCategory"] = "ARTICLE"
            share_content["media"] = [
                {
                    "status": "READY",
                    "originalUrl": image_url
                }
            ]
            
        payload = {
            "author": linkedin_author_id,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": share_content
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            }
        }
        
        if linkedin_access_token == "DEMO_MODE":
            return {"success": True, "linkedin_post_id": "demo_li_12345"}
            
        async with httpx.AsyncClient() as client:
            try:
                res = await client.post(url, headers=headers, json=payload)
                res.raise_for_status()
                return {"success": True, "linkedin_post_id": res.json().get("id")}
            except httpx.HTTPStatusError as e:
                err_detail = e.response.json()
                raise HTTPException(status_code=400, detail=f"LinkedIn API Error: {err_detail.get('message', str(e))}")
            except Exception as e:
                raise HTTPException(status_code=500, detail="Failed to communicate with LinkedIn API")
