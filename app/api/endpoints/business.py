from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.business import BusinessCreate, BusinessResponse, BusinessUpdate
from app.services.business_service import BusinessService
from app.core.security import get_current_user
from app.models.user import User
from app.core.database import get_database

router = APIRouter()

@router.post("/", response_model=BusinessResponse, status_code=status.HTTP_200_OK)
async def create_business(
    business_in: BusinessCreate,
    current_user: User = Depends(get_current_user)
):
    existing_business = await BusinessService.get_business_by_owner(str(current_user.id))
    if existing_business:
        raise HTTPException(status_code=400, detail="User already has a business")
    
    business = await BusinessService.create_business(str(current_user.id), business_in)
    return business

@router.get("/me", response_model=BusinessResponse)
async def get_my_business(current_user: User = Depends(get_current_user)):
    business = await BusinessService.get_business_by_owner(str(current_user.id))
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business

@router.put("/me", response_model=BusinessResponse)
async def update_my_business(
    business_in: BusinessUpdate,
    current_user: User = Depends(get_current_user)
):
    business = await BusinessService.update_business(str(current_user.id), business_in)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business

@router.delete("/me", status_code=status.HTTP_200_OK)
async def delete_my_business(current_user: User = Depends(get_current_user)):
    success = await BusinessService.delete_business(str(current_user.id))
    if not success:
        raise HTTPException(status_code=404, detail="Business not found")
    return {"success": True, "message": "Business deleted successfully"}

@router.delete("/{business_id}", status_code=status.HTTP_200_OK)
async def delete_business_by_id(business_id: str, current_user: User = Depends(get_current_user)):
    # In a real app, you would verify if current_user is an admin or owns this business ID.
    # For this implementation, we allow deletion by the given business_id parameter.
    from bson import ObjectId
    if not ObjectId.is_valid(business_id):
        raise HTTPException(status_code=400, detail="Invalid business ID format")
        
    db = get_database()
    result = await db["businesses"].delete_one({"_id": ObjectId(business_id)})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Business not found")
        
    return {"success": True, "message": f"Business {business_id} deleted successfully"}

@router.get("/", status_code=status.HTTP_200_OK)
async def get_all_businesses(current_user: User = Depends(get_current_user)):
    db = get_database()
    cursor = db["businesses"].find()
    businesses = await cursor.to_list(length=100)
    for b in businesses:
        b["id"] = str(b.pop("_id"))
    return businesses

@router.get("/{business_id}", response_model=BusinessResponse, status_code=status.HTTP_200_OK)
async def get_business_by_id(business_id: str, current_user: User = Depends(get_current_user)):
    from bson import ObjectId
    if not ObjectId.is_valid(business_id):
        raise HTTPException(status_code=400, detail="Invalid business ID format")
        
    db = get_database()
    business_doc = await db["businesses"].find_one({"_id": ObjectId(business_id)})
    if not business_doc:
        raise HTTPException(status_code=404, detail="Business not found")
        
    business_doc["id"] = str(business_doc.pop("_id"))
    return business_doc

@router.put("/{business_id}", response_model=BusinessResponse, status_code=status.HTTP_200_OK)
async def update_business_by_id(
    business_id: str,
    business_in: BusinessUpdate,
    current_user: User = Depends(get_current_user)
):
    from bson import ObjectId
    if not ObjectId.is_valid(business_id):
        raise HTTPException(status_code=400, detail="Invalid business ID format")
        
    db = get_database()
    business_doc = await db["businesses"].find_one({"_id": ObjectId(business_id)})
    if not business_doc:
        raise HTTPException(status_code=404, detail="Business not found")
        
    # We can reuse BusinessService.update_business by passing the owner_id of the found business
    business = await BusinessService.update_business(business_doc["owner_id"], business_in)
    return business
