import httpx
from fastapi import HTTPException
from bson import ObjectId

class SocialService:
    @staticmethod
    async def publish_to_instagram(db, business_id: str, content_id: str):
        """
        Legacy Instagram publishing via business-level tokens.
        For new integrations, prefer InstagramService (instagram_service.py)
        which uses Instagram Login with encrypted tokens.
        """
        business = await db["businesses"].find_one({"_id": ObjectId(business_id)})
        if not business:
            raise HTTPException(status_code=404, detail="Business not found")
            
        ig_account_id = business.get("ig_account_id")
        ig_access_token = business.get("ig_access_token")
        
        if not ig_account_id or not ig_access_token:
            raise HTTPException(status_code=400, detail="Instagram is not connected for this business.")
            
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
        
        if not image_url:
            import urllib.parse
            # Instagram strictly requires an image. If this content doesn't have one,
            # we will dynamically generate a beautiful fallback image based on the caption/hashtags.
            fallback_prompt = f"Beautiful background image representing: {hashtags} {caption[:50]}"
            prompt_encoded = urllib.parse.quote(fallback_prompt)
            image_url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1080&height=1080&nologo=true"
            
        if ig_access_token == "DEMO_MODE":
            print("Running in DEMO_MODE. Simulating successful Instagram publish.")
            return {"success": True, "ig_post_id": "demo_ig_12345"}
            
        async with httpx.AsyncClient() as client:
            try:
                # 1. Create Media Container (using graph.instagram.com for Instagram Login flow)
                create_url = f"https://graph.instagram.com/{ig_account_id}/media"
                payload = {
                    "image_url": image_url,
                    "caption": full_caption,
                    "access_token": ig_access_token
                }
                res = await client.post(create_url, params=payload)
                res.raise_for_status()
                creation_id = res.json().get("id")
                
                # 2. Publish Media Container
                publish_url = f"https://graph.instagram.com/{ig_account_id}/media_publish"
                pub_payload = {
                    "creation_id": creation_id,
                    "access_token": ig_access_token
                }
                pub_res = await client.post(publish_url, params=pub_payload)
                pub_res.raise_for_status()
                
                return {"success": True, "ig_post_id": pub_res.json().get("id")}
                
            except httpx.HTTPStatusError as e:
                err_detail = e.response.json()
                # Never log the access token
                raise HTTPException(status_code=400, detail=f"Instagram API Error: {err_detail.get('error', {}).get('message', str(e))}")
            except Exception as e:
                raise HTTPException(status_code=500, detail="Failed to communicate with Instagram API")

    @staticmethod
    async def publish_to_facebook(db, business_id: str, content_id: str):
        business = await db["businesses"].find_one({"_id": ObjectId(business_id)})
        if not business:
            raise HTTPException(status_code=404, detail="Business not found")
            
        fb_page_id = business.get("fb_page_id")
        fb_access_token = business.get("fb_access_token")
        
        if not fb_page_id or not fb_access_token:
            raise HTTPException(status_code=400, detail="Facebook is not connected for this business.")
            
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
        
        content_type = content.get("type", "")
        
        if fb_access_token == "DEMO_MODE":
            print("Running in DEMO_MODE. Simulating successful Facebook publish.")
            return {"success": True, "fb_post_id": "demo_fb_12345"}
            
        async with httpx.AsyncClient() as client:
            try:
                if image_url:
                    if "Reel" in content_type or "Video" in content_type or image_url.endswith(".mp4"):
                        # Publish video / reel
                        url = f"https://graph.facebook.com/v19.0/{fb_page_id}/videos"
                        payload = {
                            "file_url": image_url,
                            "description": full_caption,
                            "access_token": fb_access_token
                        }
                    else:
                        # Publish photo
                        url = f"https://graph.facebook.com/v19.0/{fb_page_id}/photos"
                        payload = {
                            "url": image_url,
                            "message": full_caption,
                            "access_token": fb_access_token
                        }
                else:
                    # Publish text only
                    url = f"https://graph.facebook.com/v19.0/{fb_page_id}/feed"
                    payload = {
                        "message": full_caption,
                        "access_token": fb_access_token
                    }
                    
                res = await client.post(url, params=payload)
                res.raise_for_status()
                
                return {"success": True, "fb_post_id": res.json().get("id")}
                
            except httpx.HTTPStatusError as e:
                err_detail = e.response.json()
                print(f"Facebook API Error: {err_detail}")
                raise HTTPException(status_code=400, detail=f"Facebook API Error: {err_detail.get('error', {}).get('message', str(e))}")
            except Exception as e:
                print(f"Failed to publish to Facebook: {e}")
                raise HTTPException(status_code=500, detail="Failed to communicate with Facebook API")

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
