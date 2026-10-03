from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import get_current_user, CurrentUser
from app.core.database import get_database
from bson import ObjectId
from datetime import datetime, timezone
from app.models.collaboration import Collaboration

router = APIRouter(prefix="/business/collaborations", tags=["Business Collaborations"])

@router.get("/applications")
async def get_incoming_applications(current_user: CurrentUser = Depends(get_current_user)):
    # Check if business user
    db = get_database()
    business = await db["businesses"].find_one({"owner_id": current_user.id})
    if not business:
        return {"success": True, "data": []}
        
    business_id = str(business["_id"])
    
    apps_cursor = db["campaign_applications"].find({"business_id": business_id, "status": "pending"}).sort("created_at", -1)
    apps = await apps_cursor.to_list(length=100)
    
    result = []
    for app in apps:
        app["id"] = str(app["_id"])
        app.pop("_id", None)
        
        # Attach influencer profile info
        inf_profile = await db["influencer_profiles"].find_one({"user_id": app["influencer_id"]})
        if inf_profile:
            app["influencer_name"] = inf_profile.get("username", "Unknown Influencer")
            app["influencer_category"] = inf_profile.get("category", "")
        else:
            app["influencer_name"] = "Unknown Influencer"
            app["influencer_category"] = ""
            
        # Attach campaign info
        camp = await db["campaigns"].find_one({"_id": ObjectId(app["campaign_id"])})
        if camp:
            app["campaign_name"] = camp.get("name", camp.get("title", "Unnamed Campaign"))
        else:
            app["campaign_name"] = "Unknown Campaign"
            
        result.append(app)
        
    return {"success": True, "data": result}

@router.put("/applications/{app_id}/status")
async def update_application_status(
    app_id: str,
    payload: dict,
    current_user: CurrentUser = Depends(get_current_user)
):
    db = get_database()
    business = await db["businesses"].find_one({"owner_id": current_user.id})
    if not business:
        return {"success": True, "data": []}
        
    if not ObjectId.is_valid(app_id):
        raise HTTPException(status_code=400, detail="Invalid ID")
        
    application = await db["campaign_applications"].find_one({"_id": ObjectId(app_id)})
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
        
    if application["business_id"] != str(business["_id"]):
        raise HTTPException(status_code=403, detail="Not authorized")
        
    new_status = payload.get("status")
    if new_status not in ["accepted", "rejected"]:
        raise HTTPException(status_code=400, detail="Invalid status")
        
    await db["campaign_applications"].update_one(
        {"_id": ObjectId(app_id)},
        {"$set": {"status": new_status, "updated_at": datetime.now(timezone.utc)}}
    )
    
    # If accepted, automatically create a collaboration
    if new_status == "accepted":
        collab = Collaboration(
            campaign_id=application["campaign_id"],
            business_id=application["business_id"],
            influencer_id=application["influencer_id"],
            application_id=app_id,
            agreed_price=application.get("proposed_price") or 0.0,
            status="active"
        )
        await db["collaborations"].insert_one(collab.model_dump(by_alias=True, exclude={"id"}))
        
    return {"success": True, "message": f"Application {new_status}"}

@router.get("")
async def get_active_collaborations(current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    business = await db["businesses"].find_one({"owner_id": current_user.id})
    if not business:
        return {"success": True, "data": []}
        
    collabs_cursor = db["collaborations"].find({"business_id": str(business["_id"])}).sort("created_at", -1)
    collabs = await collabs_cursor.to_list(length=100)
    
    result = []
    for c in collabs:
        c["id"] = str(c["_id"])
        c.pop("_id", None)
        
        # Attach influencer profile info
        inf_profile = await db["influencer_profiles"].find_one({"user_id": c["influencer_id"]})
        if inf_profile:
            c["influencer_name"] = inf_profile.get("username", "Unknown Influencer")
            
        # Attach campaign info
        camp = await db["campaigns"].find_one({"_id": ObjectId(c["campaign_id"])})
        if camp:
            c["campaign_name"] = camp.get("name", camp.get("title", "Unnamed Campaign"))
            
        result.append(c)
        
    return {"success": True, "data": result}

@router.get("/{collaboration_id}/submissions")
async def get_collaboration_submissions(
    collaboration_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    db = get_database()
    business = await db["businesses"].find_one({"owner_id": current_user.id})
    if not business:
        return {"success": True, "data": []}
        
    subs_cursor = db["content_submissions"].find({"collaboration_id": collaboration_id, "business_id": str(business["_id"])}).sort("submitted_at", -1)
    subs = await subs_cursor.to_list(length=100)
    
    result = []
    for s in subs:
        s["id"] = str(s["_id"])
        s.pop("_id", None)
        result.append(s)
        
    return {"success": True, "data": result}

@router.put("/submissions/{submission_id}/review")
async def review_submission(
    submission_id: str,
    payload: dict,
    current_user: CurrentUser = Depends(get_current_user)
):
    db = get_database()
    business = await db["businesses"].find_one({"owner_id": current_user.id})
    if not business:
        return {"success": True, "data": []}
        
    sub = await db["content_submissions"].find_one({"_id": ObjectId(submission_id)})
    if not sub or sub["business_id"] != str(business["_id"]):
        raise HTTPException(status_code=404, detail="Submission not found")
        
    status = payload.get("status")
    feedback = payload.get("feedback", "")
    
    if status not in ["approved", "changes_requested"]:
        raise HTTPException(status_code=400, detail="Invalid status")
        
    update_doc = {
        "status": status,
        "feedback": feedback
    }
    
    if status == "approved":
        update_doc["approved_at"] = datetime.now(timezone.utc)
        
    await db["content_submissions"].update_one(
        {"_id": ObjectId(submission_id)},
        {"$set": update_doc}
    )
    
    # Update collaboration status
    await db["collaborations"].update_one(
        {"_id": ObjectId(sub["collaboration_id"])},
        {"$set": {"status": status, "updated_at": datetime.now(timezone.utc)}}
    )
    
    return {"success": True, "message": f"Content {status}"}

