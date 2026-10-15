from fastapi import APIRouter, Depends, HTTPException, Body
from app.core.security import get_current_user
from app.core.database import get_database
from app.services.social_service import SocialService

router = APIRouter(
    prefix="/api/v1/social",
    tags=["Social"]
)


@router.post("/publish-instagram/{content_id}")
async def publish_instagram(
    content_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_database)
):
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user["id"]
    business_id = str(business_id)
    
    result = await SocialService.publish_to_instagram(
        db=db,
        business_id=business_id,
        content_id=content_id
    )
    
    return {"success": True, "message": "Successfully published to Instagram", "data": result}

@router.post("/publish-facebook/{content_id}")
async def publish_facebook(
    content_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_database)
):
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user["id"]
    business_id = str(business_id)
    
    result = await SocialService.publish_to_facebook(
        db=db,
        business_id=business_id,
        content_id=content_id
    )
    
    return {"success": True, "message": "Successfully published to Facebook", "data": result}

@router.post("/publish-linkedin/{content_id}")
async def publish_linkedin(
    content_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_database)
):
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user["id"]
    business_id = str(business_id)
    
    result = await SocialService.publish_to_linkedin(
        db=db,
        business_id=business_id,
        content_id=content_id
    )
    
    return {"success": True, "message": "Successfully published to LinkedIn", "data": result}


@router.post("/publish-linkedin")
async def publish_linkedin_direct(
    req: dict = Body(default={}),
    current_user = Depends(get_current_user),
    db = Depends(get_database)
):
    user_id = str(current_user.get("id") or current_user.get("_id"))
    caption = req.get("caption", "")
    image_url = req.get("image_url")
    content_id = req.get("content_id")
    business_id = current_user.get("business_id")
    
    from app.services.linkedin_service import LinkedInService
    result = await LinkedInService.publish_post(
        db=db,
        user_id=user_id,
        caption=caption,
        image_url=image_url,
        content_id=content_id,
        business_id=business_id,
    )
    return {"success": True, "message": "Successfully published to LinkedIn", "data": result}
