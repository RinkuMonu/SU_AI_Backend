import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from app.core.security import get_current_user
from app.core.database import get_database
from app.core.config import settings
import httpx

router = APIRouter(prefix="/api/facebook", tags=["Facebook"])

@router.get("/connect")
async def facebook_connect(current_user=Depends(get_current_user), db=Depends(get_database)):
    user_id = str(current_user.get("id") or current_user.get("_id"))
    state = secrets.token_urlsafe(32)
    await db["facebook_oauth_states"].insert_one({
        "state": state,
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc),
    })
    
    app_id = getattr(settings, "FACEBOOK_APP_ID", None) or getattr(settings, "INSTAGRAM_APP_ID", None)
    if not app_id:
        raise HTTPException(status_code=500, detail="Facebook/Instagram App ID not configured")
        
    redirect_uri = getattr(settings, "FACEBOOK_REDIRECT_URI", "http://localhost:8000/api/facebook/callback")
    
    scopes = "pages_show_list,pages_read_engagement,pages_manage_posts"
    auth_url = (
        f"https://www.facebook.com/v17.0/dialog/oauth"
        f"?client_id={app_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={scopes}"
        f"&state={state}"
    )
    
    return {"authorization_url": auth_url}

@router.get("/callback")
async def facebook_callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    error_reason: str = Query(None),
    error_description: str = Query(None),
    db=Depends(get_database),
):
    frontend_url = settings.CORS_ORIGINS.split(",")[0].strip()
    
    if error:
        return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error={error}")
        
    if not code:
        return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error=missing_code")
    
    # Check state
    oauth_state = await db["facebook_oauth_states"].find_one_and_delete({"state": state})
    if not oauth_state:
        return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error=invalid_state")
        
    user_id = oauth_state["user_id"]
    
    app_id = getattr(settings, "FACEBOOK_APP_ID", None) or getattr(settings, "INSTAGRAM_APP_ID", None)
    app_secret = getattr(settings, "FACEBOOK_APP_SECRET", None) or getattr(settings, "INSTAGRAM_APP_SECRET", None)
    redirect_uri = getattr(settings, "FACEBOOK_REDIRECT_URI", "http://localhost:8000/api/facebook/callback")
    
    # Exchange code for token
    async with httpx.AsyncClient() as client:
        token_url = "https://graph.facebook.com/v17.0/oauth/access_token"
        params = {
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": code
        }
        res = await client.get(token_url, params=params)
        
        if res.status_code != 200:
            return RedirectResponse(f"{frontend_url}/social-platforms/facebook?error=token_exchange_failed")
            
        data = res.json()
        access_token = data.get("access_token")
        
        # In a real app we'd fetch the user's pages and exchange for a page token
        # For now we'll just save the user access token and let the frontend/backend use it
        
        await db.businesses.update_one(
            {"user_id": user_id},
            {"$set": {"fb_access_token": access_token}},
            upsert=True
        )
        
    return RedirectResponse(
        url=f"{frontend_url}/social-platforms/facebook?facebook_connected=true&fb_access_token={access_token}"
    )
