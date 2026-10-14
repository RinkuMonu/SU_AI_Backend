
from fastapi import APIRouter, Depends, status, HTTPException, UploadFile, File
from app.core.security import get_current_user, CurrentUser, verify_password, get_password_hash
from app.core.database import get_database
from app.schemas.user import UserResponse, UserPreferencesUpdate, UserUpdate, ChangePasswordRequest
from app.utils.upload import save_image
from bson import ObjectId

router = APIRouter()

@router.get("/me")
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    user_id = current_user.get("id") or current_user.get("_id")
    doc = None
    try:
        doc = await db["users"].find_one({"_id": ObjectId(str(user_id))})
    except Exception:
        pass
    if not doc and current_user.get("email"):
        doc = await db["users"].find_one({"email": current_user.get("email")})

    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
        
    doc["id"] = str(doc["_id"])
    del doc["_id"]
    if "hashed_password" in doc:
        del doc["hashed_password"]

    # Provide field normalization & compatibility
    if not doc.get("name") and doc.get("fullName"):
        doc["name"] = doc["fullName"]
    if not doc.get("fullName") and doc.get("name"):
        doc["fullName"] = doc["name"]
    if not doc.get("image") and doc.get("profileImageUrl"):
        doc["image"] = doc["profileImageUrl"]
    if not doc.get("profileImageUrl") and doc.get("image"):
        doc["profileImageUrl"] = doc["image"]
    if not doc.get("contactNumber") and doc.get("phone"):
        doc["contactNumber"] = doc["phone"]
    if not doc.get("phone") and doc.get("contactNumber"):
        doc["phone"] = doc["contactNumber"]
    if not doc.get("role"):
        doc["role"] = "user"

    return {
        "success": True,
        "data": doc
    }

@router.patch("/me")
async def update_me(req: UserUpdate, current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    user_id = current_user.get("id") or current_user.get("_id")
    update_data = req.model_dump(exclude_unset=True)

    if update_data:
        # Reconstruct fullName / name if firstName or lastName provided
        first = update_data.get("firstName")
        last = update_data.get("lastName")
        if first is not None or last is not None:
            user_doc = None
            try:
                user_doc = await db["users"].find_one({"_id": ObjectId(str(user_id))})
            except Exception:
                pass
            cur_first = first if first is not None else (user_doc.get("firstName") if user_doc else "")
            cur_last = last if last is not None else (user_doc.get("lastName") if user_doc else "")
            full = f"{cur_first or ''} {cur_last or ''}".strip()
            if full:
                update_data["fullName"] = full
                update_data["name"] = full

        # Reconcile phone & contactNumber
        if "contactNumber" in update_data and "phone" not in update_data:
            update_data["phone"] = update_data["contactNumber"]
        elif "phone" in update_data and "contactNumber" not in update_data:
            update_data["contactNumber"] = update_data["phone"]

        # Reconcile image & profileImageUrl
        if "image" in update_data and "profileImageUrl" not in update_data:
            update_data["profileImageUrl"] = update_data["image"]
        elif "profileImageUrl" in update_data and "image" not in update_data:
            update_data["image"] = update_data["profileImageUrl"]

        await db["users"].update_one(
            {"_id": ObjectId(str(user_id))},
            {"$set": update_data}
        )
    
    doc = await db["users"].find_one({"_id": ObjectId(str(user_id))})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
        
    doc["id"] = str(doc["_id"])
    del doc["_id"]
    if "hashed_password" in doc:
        del doc["hashed_password"]

    if not doc.get("name") and doc.get("fullName"):
        doc["name"] = doc["fullName"]
    if not doc.get("fullName") and doc.get("name"):
        doc["fullName"] = doc["name"]
    if not doc.get("image") and doc.get("profileImageUrl"):
        doc["image"] = doc["profileImageUrl"]
    if not doc.get("profileImageUrl") and doc.get("image"):
        doc["profileImageUrl"] = doc["image"]

    return {
        "success": True,
        "message": "User updated successfully",
        "data": doc
    }

@router.post("/me/change-password")
async def change_password(req: ChangePasswordRequest, current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    user_id = current_user.get("id") or current_user.get("_id")
    user_doc = await db["users"].find_one({"_id": ObjectId(str(user_id))})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(req.currentPassword, user_doc.get("hashed_password", "")):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if len(req.newPassword) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    if req.confirmPassword and req.newPassword != req.confirmPassword:
        raise HTTPException(status_code=400, detail="New passwords do not match")

    new_hash = get_password_hash(req.newPassword)
    await db["users"].update_one(
        {"_id": ObjectId(str(user_id))},
        {"$set": {"hashed_password": new_hash}}
    )
    return {
        "success": True,
        "message": "Password changed successfully"
    }

@router.post("/me/avatar")
async def upload_avatar(file: UploadFile = File(...), current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    user_id = current_user.get("id") or current_user.get("_id")
    image_url = await save_image(file, "avatars")
    
    await db["users"].update_one(
        {"_id": ObjectId(str(user_id))},
        {"$set": {"profileImageUrl": image_url, "image": image_url}}
    )

    return {
        "success": True,
        "message": "Avatar uploaded successfully",
        "image_url": image_url
    }

@router.patch("/me/preferences")
async def update_preferences(req: UserPreferencesUpdate, current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    user_id = current_user.get("id") or current_user.get("_id")
    update_data = req.model_dump(exclude_unset=True)
    if update_data:
        await db["users"].update_one(
            {"_id": ObjectId(str(user_id))},
            {"$set": update_data}
        )
    
    return {
        "success": True,
        "message": "Preferences updated successfully"
    }
