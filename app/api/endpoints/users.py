from fastapi import APIRouter, Depends, status, HTTPException, UploadFile, File
from app.core.security import get_current_user, CurrentUser, verify_password, get_password_hash
from app.core.database import get_database
from app.schemas.user import UserResponse, UserPreferencesUpdate, UserUpdate, ChangePasswordRequest
from app.utils.upload import save_image
from bson import ObjectId

router = APIRouter()

from app.services.auth_service import AuthService

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
        doc = await db["pending_users"].find_one({"_id": ObjectId(current_user["id"])})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
        
    doc["id"] = str(doc["_id"])
    del doc["_id"]
    if "hashed_password" in doc:
        del doc["hashed_password"]

    # Provide field normalization & compatibility in response
    canonical_name = doc.get("name") or doc.get("fullName") or "User"
    doc["name"] = canonical_name
    doc["fullName"] = canonical_name
    parts = canonical_name.split() if canonical_name != "User" else []
    doc["firstName"] = doc.get("firstName") or (parts[0] if parts else "")
    doc["lastName"] = doc.get("lastName") or (" ".join(parts[1:]) if len(parts) > 1 else "")
    parts = canonical_name.split() if canonical_name != "User" else []
    doc["firstName"] = doc.get("firstName") or (parts[0] if parts else "")
    doc["lastName"] = doc.get("lastName") or (" ".join(parts[1:]) if len(parts) > 1 else "")

    canonical_phone = doc.get("phone_number") or doc.get("phone") or doc.get("contactNumber")
    doc["phone_number"] = canonical_phone
    doc["phone"] = canonical_phone
    doc["contactNumber"] = canonical_phone

    canonical_email_verified = doc.get("email_verified", doc.get("emailVerified", False))
    doc["email_verified"] = canonical_email_verified
    doc["emailVerified"] = canonical_email_verified

    if not doc.get("image") and doc.get("profileImageUrl"):
        doc["image"] = doc["profileImageUrl"]
    if not doc.get("profileImageUrl") and doc.get("image"):
        doc["profileImageUrl"] = doc["image"]
    if not doc.get("role"):
        doc["role"] = "user"

    services = doc.get("selected_services") or doc.get("selectedServices") or []
    doc["selected_services"] = services
    doc["selectedServices"] = services

    return {
        "success": True,
        "data": doc
    }

@router.patch("/me")
@router.put("/me")
async def update_me(req: UserUpdate, current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    user_id = str(current_user.get("id") or current_user.get("_id"))
    update_data = req.model_dump(exclude_unset=True)

    if update_data:
        user_doc = None
        try:
            if ObjectId.is_valid(user_id):
                user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
                if not user_doc:
                    user_doc = await db["pending_users"].find_one({"_id": ObjectId(user_id)})
        except Exception:
            pass

        first = update_data.get("firstName")
        last = update_data.get("lastName")
        name_val = update_data.get("name") or update_data.get("fullName")

        if first is not None or last is not None:
            cur_first = str(first if first is not None else (user_doc.get("firstName") if user_doc else "")).strip()
            cur_last = str(last if last is not None else (user_doc.get("lastName") if user_doc else "")).strip()
            full = f"{cur_first} {cur_last}".strip()
            if full:
                update_data["name"] = full
                update_data["fullName"] = full
                update_data["firstName"] = cur_first
                update_data["lastName"] = cur_last
        elif name_val and str(name_val).strip():
            clean_name = str(name_val).strip()
            update_data["name"] = clean_name
            update_data["fullName"] = clean_name
            parts = clean_name.split()
            update_data["firstName"] = parts[0] if parts else ""
            update_data["lastName"] = " ".join(parts[1:]) if len(parts) > 1 else ""

        # Reconcile phone & contactNumber to canonical phone_number
        if "phone" in update_data or "contactNumber" in update_data or "phone_number" in update_data:
            p_val = update_data.get("phone_number") or update_data.get("phone") or update_data.get("contactNumber")
            if p_val:
                update_data["phone_number"] = p_val
            update_data.pop("phone", None)
            update_data.pop("contactNumber", None)

        # Reconcile image & profileImageUrl
        if "image" in update_data and "profileImageUrl" not in update_data:
            update_data["profileImageUrl"] = update_data["image"]
        elif "profileImageUrl" in update_data and "image" not in update_data:
            update_data["image"] = update_data["profileImageUrl"]

    is_pending = current_user.get("is_pending", False)
    if not is_pending:
        pending_check = await db["pending_users"].find_one({"_id": ObjectId(user_id)})
        if pending_check:
            is_pending = True

    # If onboarding is completed, commit user to users collection permanently!
    if update_data.get("onboardingCompleted") == True:
        doc = await AuthService.commit_pending_user(user_id, update_data)
    else:
        # Always persist updates to canonical users collection
        if update_data:
            await db["users"].update_one(
                {"_id": ObjectId(user_id)},
                {"$set": update_data}
            )
            # Also update pending_users if record exists there
            if is_pending:
                await db["pending_users"].update_one(
                    {"_id": ObjectId(user_id)},
                    {"$set": update_data}
                )
        doc = await db["users"].find_one({"_id": ObjectId(user_id)})
        if not doc and is_pending:
            doc = await db["pending_users"].find_one({"_id": ObjectId(user_id)})
    
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")

    doc["id"] = str(doc["_id"])
    del doc["_id"]
    if "hashed_password" in doc:
        del doc["hashed_password"]

    canonical_name = doc.get("name") or doc.get("fullName") or "User"
    doc["name"] = canonical_name
    doc["fullName"] = canonical_name
    parts = canonical_name.split() if canonical_name != "User" else []
    doc["firstName"] = doc.get("firstName") or (parts[0] if parts else "")
    doc["lastName"] = doc.get("lastName") or (" ".join(parts[1:]) if len(parts) > 1 else "")
    parts = canonical_name.split() if canonical_name != "User" else []
    doc["firstName"] = doc.get("firstName") or (parts[0] if parts else "")
    doc["lastName"] = doc.get("lastName") or (" ".join(parts[1:]) if len(parts) > 1 else "")

    canonical_phone = doc.get("phone_number") or doc.get("phone") or doc.get("contactNumber")
    doc["phone_number"] = canonical_phone
    doc["phone"] = canonical_phone
    doc["contactNumber"] = canonical_phone

    canonical_email_verified = doc.get("email_verified", doc.get("emailVerified", False))
    doc["email_verified"] = canonical_email_verified
    doc["emailVerified"] = canonical_email_verified

    if not doc.get("image") and doc.get("profileImageUrl"):
        doc["image"] = doc["profileImageUrl"]
    if not doc.get("profileImageUrl") and doc.get("image"):
        doc["profileImageUrl"] = doc["image"]

    return {
        "success": True,
        "message": "User updated successfully",
        "data": doc
    }

@router.post("/me/avatar")
async def upload_avatar(file: UploadFile = File(...), current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    user_id = str(current_user.get("id") or current_user.get("_id"))
    image_url = await save_image(file, "avatars")
    await db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"profileImageUrl": image_url, "image": image_url}}
    )
    if current_user.get("is_pending"):
        await db["pending_users"].update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"profileImageUrl": image_url, "image": image_url}}
        )
    doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    if not doc and current_user.get("is_pending"):
        doc = await db["pending_users"].find_one({"_id": ObjectId(user_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    doc["id"] = str(doc["_id"])
    del doc["_id"]
    return {
        "success": True,
        "message": "Avatar uploaded successfully",
        "image_url": image_url,
        "data": doc
    }

@router.post("/me/change-password")
async def change_password(req: ChangePasswordRequest, current_user: CurrentUser = Depends(get_current_user)):
    db = get_database()
    user_id = str(current_user.get("id") or current_user.get("_id"))
    doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    
    current_hashed = doc.get("hashed_password", "")
    if not verify_password(req.currentPassword, current_hashed):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(req.newPassword) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters long")
    if req.confirmPassword and req.newPassword != req.confirmPassword:
        raise HTTPException(status_code=400, detail="New passwords do not match")
    
    new_hashed = get_password_hash(req.newPassword)
    await db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"hashed_password": new_hashed}}
    )
    return {
        "success": True,
        "message": "Password changed successfully"
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
