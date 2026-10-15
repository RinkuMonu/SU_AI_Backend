import httpx
from fastapi import HTTPException
from bson import ObjectId

class SocialService:
    @staticmethod
    async def publish_to_instagram(db, business_id: str, content_id: str):
        """
        Unified Instagram publishing via InstagramService.
        Checks businesses, users, and instagram_connections for credentials,
        and updates contents collection with published post ID and status.
        """
        from app.services.instagram_service import InstagramService

        query = {"_id": ObjectId(content_id)} if ObjectId.is_valid(content_id) else {"_id": content_id}
        content = await db["contents"].find_one(query)
        if not content and ObjectId.is_valid(content_id):
            content = await db["contents"].find_one({"_id": str(content_id)})
        if not content:
            raise HTTPException(status_code=404, detail="Content not found")

        image_url = content.get("image_url") or content.get("media_url") or content.get("imageUrl")
        caption = content.get("caption", "")
        hashtags = content.get("hashtags", "")
        if isinstance(hashtags, list):
            hashtags = " ".join(hashtags)
        full_caption = f"{caption}\n\n{hashtags}".strip()

        if not image_url:
            image_url = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1080&q=80"

                # Check active user connection first, then content user_id
        effective_user_id = str(business_id)
        conn = await InstagramService.get_connection(db, effective_user_id)
        if not conn and content.get("user_id"):
            content_user_id = str(content.get("user_id"))
            conn_content = await InstagramService.get_connection(db, content_user_id)
            if conn_content:
                effective_user_id = content_user_id

        return await InstagramService.publish_image(
            db=db,
            user_id=effective_user_id,
            image_url=image_url,
            caption=full_caption,
            content_id=content_id,
        )

    @staticmethod
    async def publish_to_facebook(db, business_id: str, content_id: str):
        from app.services.facebook_service import FacebookService
        
        query = {"_id": ObjectId(content_id)} if ObjectId.is_valid(content_id) else {"_id": content_id}
        content = await db["contents"].find_one(query)
        if not content and ObjectId.is_valid(content_id):
            content = await db["contents"].find_one({"_id": str(content_id)})
        if not content:
            raise HTTPException(status_code=404, detail="Content not found")
            
        image_url = content.get("image_url") or content.get("media_url") or content.get("imageUrl")
        caption = content.get("caption", "")
        hashtags = content.get("hashtags", "")
        if isinstance(hashtags, list):
            hashtags = " ".join(hashtags)
        full_caption = f"{caption}\n\n{hashtags}".strip()
        
        user_id = content.get("user_id") or business_id
        return await FacebookService.publish_post(
            db=db,
            user_id=str(user_id),
            caption=full_caption,
            image_url=image_url,
            content_id=content_id,
        )

    @staticmethod
    async def publish_to_linkedin(db, business_id: str, content_id: str):
        business = await db["businesses"].find_one({"_id": ObjectId(business_id)})
        if not business:
            raise HTTPException(status_code=404, detail="Business not found")
            
        linkedin_author_id = business.get("linkedin_author_id")
        linkedin_access_token = business.get("linkedin_access_token")
        
        if not linkedin_author_id or not linkedin_access_token:
            raise HTTPException(status_code=400, detail="LinkedIn is not connected for this business.")
            
        content = await db["contents"].find_one({
            "_id": ObjectId(content_id),
            "business_id": business_id
        })
        
        if not content:
            raise HTTPException(status_code=404, detail="Content not found")
            
        image_url = content.get("image_url")
        caption = content.get("caption", "")
        hashtags = content.get("hashtags", "")
        full_caption = f"{caption}\n\n{hashtags}"
        
        url = "https://api.linkedin.com/v2/ugcPosts"
        headers = {
            "Authorization": f"Bearer {linkedin_access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json"
        }
        
        # We will do a simple article share if there is an image, otherwise a text share.
        # LinkedIn UGC Posts:
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
            print("Running in DEMO_MODE. Simulating successful LinkedIn publish.")
            return {"success": True, "linkedin_post_id": "demo_li_12345"}
            
        async with httpx.AsyncClient() as client:
            try:
                res = await client.post(url, headers=headers, json=payload)
                res.raise_for_status()
                return {"success": True, "linkedin_post_id": res.json().get("id")}
            except httpx.HTTPStatusError as e:
                err_detail = e.response.json()
                print(f"LinkedIn API Error: {err_detail}")
                raise HTTPException(status_code=400, detail=f"LinkedIn API Error: {err_detail.get('message', str(e))}")
            except Exception as e:
                print(f"Failed to publish to LinkedIn: {e}")
                raise HTTPException(status_code=500, detail="Failed to communicate with LinkedIn API")
