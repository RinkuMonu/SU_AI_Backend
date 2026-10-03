from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import get_current_user, CurrentUser
from app.core.database import get_database
from bson import ObjectId
from datetime import datetime, timezone
from app.models.content_submission import ContentSubmission

router = APIRouter(prefix="/influencer/content", tags=["Influencer Content"])

@router.get("")
async def get_my_submissions(current_user: CurrentUser = Depends(get_current_user)):
    if current_user.role != "influencer":
        return {"success": False, "message": "Only influencers can access", "data": []}
        
    db = get_database()
    cursor = db["content_submissions"].find({"influencer_id": current_user.id}).sort("submitted_at", -1)
    subs = await cursor.to_list(length=100)
    
    result = []
    for s in subs:
        s["id"] = str(s["_id"])
        s.pop("_id", None)
        result.append(s)
        
    return {"success": True, "data": result}

@router.post("/{collaboration_id}")
async def submit_content(
    collaboration_id: str,
    payload: dict,
    current_user: CurrentUser = Depends(get_current_user)
):
    if current_user.role != "influencer":
        return {"success": False, "message": "Only influencers can access", "data": []}
        
    db = get_database()
    
    if not ObjectId.is_valid(collaboration_id):
        raise HTTPException(status_code=400, detail="Invalid ID")
        
    collab = await db["collaborations"].find_one({"_id": ObjectId(collaboration_id)})
    if not collab:
        raise HTTPException(status_code=404, detail="Collaboration not found")
        
    if collab["influencer_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not your collaboration")
        
    sub = ContentSubmission(
        collaboration_id=collaboration_id,
        influencer_id=current_user.id,
        business_id=collab["business_id"],
        content_type=payload.get("content_type", "image"),
        media_url=payload.get("media_url", ""),
        caption=payload.get("caption", ""),
        hashtags=payload.get("hashtags", ""),
        platform=payload.get("platform", "instagram")
    )
    
    doc = sub.model_dump(by_alias=True, exclude={"id"})
    await db["content_submissions"].insert_one(doc)
    
    # Update collaboration status
    await db["collaborations"].update_one(
        {"_id": ObjectId(collaboration_id)},
        {"$set": {"status": "content_submitted", "updated_at": datetime.now(timezone.utc)}}
    )
    
    return {"success": True, "message": "Content submitted for review"}

@router.put("/{submission_id}/live-url")
async def update_live_url(
    submission_id: str,
    payload: dict,
    current_user: CurrentUser = Depends(get_current_user)
):
    if current_user.role != "influencer":
        return {"success": False, "message": "Only influencers can access", "data": []}
        
    db = get_database()
    sub = await db["content_submissions"].find_one({"_id": ObjectId(submission_id)})
    
    if not sub or sub["influencer_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Submission not found")
        
    await db["content_submissions"].update_one(
        {"_id": ObjectId(submission_id)},
        {
            "$set": {
                "live_url": payload.get("live_url"),
                "status": "published",
                "published_at": datetime.now(timezone.utc)
            }
        }
    )
    
    # Update collaboration
    await db["collaborations"].update_one(
        {"_id": ObjectId(sub["collaboration_id"])},
        {"$set": {"status": "completed", "updated_at": datetime.now(timezone.utc)}}
    )
    
    return {"success": True, "message": "Live URL saved and collaboration marked as completed"}

