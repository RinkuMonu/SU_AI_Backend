
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

@router.get("/{id}")
async def get_business(id: str, current_user: CurrentUser = Depends(get_current_user)):
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
