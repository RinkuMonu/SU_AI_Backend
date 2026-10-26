from fastapi import APIRouter, Depends, status, HTTPException
from app.core.security import get_current_user, CurrentUser
from app.core.database import get_database
from app.schemas.business import BusinessCreate, BusinessUpdate, BusinessResponse
from app.models.business import Business
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter()

@router.post("/")
async def create_business(req: BusinessCreate, current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    uid = str(current_user["id"])
    now = datetime.now(timezone.utc)
    
    # Auto-upgrade user account type and role to business/businessman
    if ObjectId.is_valid(uid):
        await db["users"].update_one(
            {"_id": ObjectId(uid)},
            {"$set": {"accountType": "business", "role": "businessman", "updated_at": now}}
        )
        await db["pending_users"].update_one(
            {"_id": ObjectId(uid)},
            {"$set": {"accountType": "business", "role": "businessman", "updated_at": now}}
        )

    # Check existing business by ownerId or owner_id
    existing = await db["businesses"].find_one({
        "$or": [
            {"ownerId": uid},
            {"owner_id": uid},
            {"ownerId": ObjectId(uid) if ObjectId.is_valid(uid) else uid},
            {"owner_id": ObjectId(uid) if ObjectId.is_valid(uid) else uid}
        ]
    })
    
    update_data = req.model_dump(exclude_none=True)
    update_data["updated_at"] = now
    
    if existing:
        await db["businesses"].update_one(
            {"_id": existing["_id"]},
            {"$set": update_data}
        )
        updated = await db["businesses"].find_one({"_id": existing["_id"]})
        updated["id"] = str(updated.pop("_id"))
        return {
            "success": True,
            "message": "Business profile updated successfully",
            "data": updated
        }

    business = Business(
        ownerId=uid,
        **req.model_dump()
    )
    doc = business.model_dump(by_alias=True, exclude={"id"})
    doc["owner_id"] = uid
    doc["created_at"] = now
    doc["updated_at"] = now
    res = await db["businesses"].insert_one(doc)
    doc["id"] = str(res.inserted_id)
    doc.pop("_id", None)
    return {
        "success": True,
        "message": "Business created successfully",
        "data": doc
    }


@router.get("/")
async def get_businesses(current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    docs = await db["businesses"].find({"ownerId": current_user["id"]}).to_list(length=100)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return {
        "success": True,
        "data": docs
    }

@router.get("/me")
async def get_my_business(current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    owner_str = str(current_user["id"])
    owner_oid = ObjectId(owner_str) if ObjectId.is_valid(owner_str) else owner_str
    
    # 1. Fetch user document to read social credentials or basic user details
    user_doc = await db["users"].find_one({"_id": owner_oid}) if ObjectId.is_valid(owner_str) else None
    
    query = {
        "$or": [
            {"ownerId": owner_str},
            {"ownerId": owner_oid},
            {"owner_id": owner_str},
            {"owner_id": owner_oid},
            {"user_id": owner_str},
            {"user_id": owner_oid},
            {"userId": owner_str},
            {"userId": owner_oid},
        ]
    }
    doc = await db["businesses"].find_one(query)
    
    # Check linkedin_connections for active LinkedIn
    conn = await db["linkedin_connections"].find_one({"user_id": owner_str})
    if not conn and user_doc and user_doc.get("email"):
        conn = await db["linkedin_connections"].find_one({"email": user_doc["email"]})

    if not doc:
        now = datetime.now(timezone.utc)
        user_name = (user_doc.get("fullName") or user_doc.get("name") or "My") if user_doc else "My"
        new_biz = {
            "ownerId": owner_str,
            "owner_id": owner_str,
            "userId": owner_str,
            "user_id": owner_str,
            "businessName": f"{user_name}'s Business" if user_name != "My" else "My Business",
            "business_name": f"{user_name}'s Business" if user_name != "My" else "My Business",
            "businessType": "Retail",
            "industry": "General",
            "created_at": now,
            "updated_at": now,
        }
        # Populate social tokens if available on user or connections
        if user_doc:
            if user_doc.get("linkedin_author_id"):
                new_biz["linkedin_author_id"] = user_doc["linkedin_author_id"]
            if user_doc.get("linkedin_access_token"):
                new_biz["linkedin_access_token"] = user_doc["linkedin_access_token"]
            if user_doc.get("linkedin_connected") is not None:
                new_biz["linkedin_connected"] = user_doc["linkedin_connected"]
            if user_doc.get("instagram_access_token"):
                new_biz["instagram_access_token"] = user_doc["instagram_access_token"]
            if user_doc.get("fb_page_access_token"):
                new_biz["fb_page_access_token"] = user_doc["fb_page_access_token"]
                new_biz["fb_access_token"] = user_doc["fb_page_access_token"]
            if user_doc.get("fb_page_id"):
                new_biz["fb_page_id"] = user_doc["fb_page_id"]

        if conn and conn.get("connected"):
            if not new_biz.get("linkedin_author_id") and conn.get("author_id"):
                new_biz["linkedin_author_id"] = conn["author_id"]
            if not new_biz.get("linkedin_access_token") and conn.get("access_token"):
                new_biz["linkedin_access_token"] = conn["access_token"]
            new_biz["linkedin_connected"] = True

        res = await db["businesses"].insert_one(new_biz)
        doc = await db["businesses"].find_one({"_id": res.inserted_id})
    else:
        # If business doc exists but missing LinkedIn tokens, sync from user_doc or conn
        sync_updates = {}
        if not doc.get("linkedin_author_id"):
            li_author = (user_doc and user_doc.get("linkedin_author_id")) or (conn and conn.get("author_id"))
            if li_author:
                sync_updates["linkedin_author_id"] = li_author
        if not doc.get("linkedin_access_token"):
            li_token = (user_doc and user_doc.get("linkedin_access_token")) or (conn and conn.get("access_token"))
            if li_token:
                sync_updates["linkedin_access_token"] = li_token
        if not doc.get("linkedin_connected"):
            if (user_doc and user_doc.get("linkedin_connected")) or (conn and conn.get("connected")):
                sync_updates["linkedin_connected"] = True
            elif sync_updates.get("linkedin_author_id") and sync_updates.get("linkedin_access_token"):
                sync_updates["linkedin_connected"] = True

        if sync_updates:
            await db["businesses"].update_one({"_id": doc["_id"]}, {"$set": sync_updates})
            doc.update(sync_updates)

    doc["id"] = str(doc.pop("_id"))
    return {
        "success": True,
        "data": doc,
        **doc
    }

@router.put("/me")
async def update_my_business(req: dict, current_user: CurrentUser = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    db = get_database()
    owner_str = str(current_user["id"])
    owner_oid = ObjectId(owner_str) if ObjectId.is_valid(owner_str) else owner_str
    query = {
        "$or": [
            {"ownerId": owner_str},
            {"ownerId": owner_oid},
            {"owner_id": owner_str},
            {"owner_id": owner_oid},
            {"user_id": owner_str},
            {"user_id": owner_oid},
            {"userId": owner_str},
            {"userId": owner_oid},
        ]
    }
    clean_req = {k: v for k, v in req.items() if v is not None}
    clean_req["updated_at"] = now
    
    # Always allow upsert so that settings saved from social integration pages are NEVER lost
    await db["businesses"].update_one(
        query,
        {
            "$set": clean_req,
            "$setOnInsert": {
                "ownerId": owner_str,
                "owner_id": owner_str,
                "userId": owner_str,
                "user_id": owner_str,
                "businessName": clean_req.get("businessName") or clean_req.get("business_name") or "My Business",
                "business_name": clean_req.get("business_name") or clean_req.get("businessName") or "My Business",
                "businessType": "Retail",
                "industry": "General",
                "created_at": now,
            }
        },
        upsert=True
    )
    
    # Sync LinkedIn credentials to users and linkedin_connections if present
    li_author = clean_req.get("linkedin_author_id")
    li_token = clean_req.get("linkedin_access_token")
    li_connected = clean_req.get("linkedin_connected")
    if li_author is not None or li_token is not None or li_connected is not None:
        user_update = {"updated_at": now}
        if li_author is not None:
            user_update["linkedin_author_id"] = li_author
            li_id = li_author.replace("urn:li:person:", "") if "urn:li:person:" in str(li_author) else li_author
            user_update["linkedinId"] = li_id
            user_update["linkedin_id"] = li_id
        if li_token is not None:
            user_update["linkedin_access_token"] = li_token
        if li_connected is not None:
            user_update["linkedin_connected"] = bool(li_connected)
        if ObjectId.is_valid(owner_str):
            await db["users"].update_one({"_id": owner_oid}, {"$set": user_update})
            
        if li_author or li_token:
            await db["linkedin_connections"].update_one(
                {"user_id": owner_str},
                {"$set": {
                    "user_id": owner_str,
                    "platform": "linkedin",
                    "author_id": li_author or "",
                    "access_token": li_token or "",
                    "connected": bool(li_connected if li_connected is not None else (li_author and li_token)),
                    "updated_at": now,
                }},
                upsert=True
            )
        elif li_connected is False or (li_author == "" and li_token == ""):
            await db["linkedin_connections"].delete_one({"user_id": owner_str})

    doc = await db["businesses"].find_one(query)
    if doc:
        doc["id"] = str(doc.pop("_id"))
    return {
        "success": True,
        "message": "Business updated successfully",
        "data": doc,
        **(doc or {})
    }

@router.get("/{id}")
async def get_business(id: str, current_user: CurrentUser = Depends(get_current_user)):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=404, detail="Invalid business ID format")
    db = get_database()
    doc = await db["businesses"].find_one({"_id": ObjectId(id), "ownerId": current_user["id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Business not found")
    doc["id"] = str(doc.pop("_id"))
    return {
        "success": True,
        "data": doc
    }

@router.patch("/{id}")
async def update_business(id: str, req: BusinessUpdate, current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    doc = await db["businesses"].find_one({"_id": ObjectId(id), "ownerId": current_user["id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Business not found")
        
    update_data = req.model_dump(exclude_unset=True)
    if update_data:
        await db["businesses"].update_one(
            {"_id": ObjectId(id)},
            {"$set": update_data}
        )
    
    doc = await db["businesses"].find_one({"_id": ObjectId(id)})
    doc["id"] = str(doc.pop("_id"))
    return {
        "success": True,
        "message": "Business updated successfully",
        "data": doc
    }

@router.delete("/{id}")
async def delete_business(id: str, current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    result = await db["businesses"].delete_one({"_id": ObjectId(id), "ownerId": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Business not found")
    return {
        "success": True,
        "message": "Business deleted successfully"
    }
