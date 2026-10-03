from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import get_current_user, CurrentUser
from app.core.database import get_database
from bson import ObjectId

router = APIRouter(prefix="/influencer/earnings", tags=["Influencer Earnings"])

@router.get("")
async def get_my_earnings(current_user: CurrentUser = Depends(get_current_user)):
    if current_user.role != "influencer":
        return {"success": False, "message": "Only influencers can access", "data": {"earnings": [], "summary": {"total_pending": 0, "total_paid": 0, "total_earned": 0}}}
        
    db = get_database()
    collabs_cursor = db["collaborations"].find({"influencer_id": current_user.id}).sort("created_at", -1)
    collabs = await collabs_cursor.to_list(length=100)
    
    earnings = []
    total_pending = 0
    total_paid = 0
    
    for c in collabs:
        status_val = "pending"
        if c.get("status") in ["published", "completed"]:
            status_val = "approved"  # or paid
            
        camp_name = "Unknown Campaign"
        business_name = "Unknown Brand"
        
        camp = await db["campaigns"].find_one({"_id": ObjectId(c["campaign_id"])})
        if camp:
            camp_name = camp.get("name", camp.get("title", "Unnamed Campaign"))
            biz_id = camp.get("business_id")
            if biz_id and ObjectId.is_valid(biz_id):
                biz = await db["businesses"].find_one({"_id": ObjectId(biz_id)})
                if biz:
                    business_name = biz.get("name", "Unknown Brand")
                    
        amt = c.get("agreed_price", 0)
        
        if status_val == "pending":
            total_pending += amt
        else:
            total_paid += amt
            
        earnings.append({
            "id": str(c["_id"]),
            "collaboration_id": str(c["_id"]),
            "campaign_name": camp_name,
            "business_name": business_name,
            "amount": amt,
            "status": status_val,
            "created_at": c.get("created_at")
        })
        
    return {
        "success": True, 
        "data": {
            "earnings": earnings,
            "summary": {
                "total_pending": total_pending,
                "total_paid": total_paid,
                "total_earned": total_pending + total_paid
            }
        }
    }

