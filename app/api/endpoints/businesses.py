
from fastapi import APIRouter, Depends, status, HTTPException
from app.core.security import get_current_user, CurrentUser
from app.core.database import get_database
from app.schemas.business import BusinessCreate, BusinessUpdate, BusinessResponse
from app.models.business import Business
from bson import ObjectId

router = APIRouter()

@router.post("/")
async def create_business(req: BusinessCreate, current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    if current_user["accountType"] != "business":
        raise HTTPException(status_code=403, detail="Personal users cannot create business profiles")
        
    existing = await db["businesses"].find_one({"ownerId": current_user["id"]})
    if existing:
        raise HTTPException(status_code=409, detail="Business profile already exists for this user")
        
    business = Business(
        ownerId=current_user["id"],
        **req.model_dump()
    )
    doc = business.model_dump(by_alias=True, exclude={"id"})
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
    doc = await db["businesses"].find_one({
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
    })
    if not doc:
        return {"success": True, "data": None}
    doc["id"] = str(doc.pop("_id"))
    return {
        "success": True,
        "data": doc,
        **doc
    }

@router.put("/me")
async def update_my_business(req: dict, current_user: CurrentUser = Depends(get_current_user)):
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
    if clean_req:
        await db["businesses"].update_one(query, {"$set": clean_req}, upsert=True)
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
