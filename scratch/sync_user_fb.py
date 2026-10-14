import sys
sys.path.insert(0, ".")
import asyncio
from bson import ObjectId
from app.core.database import connect_to_mongo, get_database, close_mongo_connection
from app.services.facebook_service import encrypt_token

async def sync():
    connect_to_mongo()
    db = get_database()
    
    # 1. Get the tokens from the latest connected business 6ace05ca1e06924210923576
    src = await db['businesses'].find_one({"_id": ObjectId("6ace05ca1e06924210923576")})
    if not src:
        print("Source not found!")
        close_mongo_connection()
        return

    page_id = src.get("fb_page_id")
    page_name = src.get("fb_page_name")
    page_token = "EAAWmVMwnqgABSkH99XuQmc2Dtb2rZCR7dHKjwF5RRC1TNo8PTZAnLRqOg9TVkOZA6dIwFkhunZAriZChYZBb04MR5p72yrrMZB2deGgJEWx0rEmtGTG8uTj88IcZCNkZCBe73XNGd4QvsmXi1uoZCIxJQmEgfIDxiq0a5pv9f29FxSZCoGuHQB5U98tZCRFmP4L5zZBkhhadZBNMuE"
    user_token = src.get("fb_user_access_token")
    pages = src.get("fb_pages")
    expires_at = src.get("fb_token_expires_at")
    
    update_data = {
        "fb_connected": True,
        "fb_page_id": page_id,
        "fb_page_name": page_name,
        "fb_access_token": page_token,
        "fb_page_access_token": page_token,
        "fb_access_token_encrypted": encrypt_token(page_token),
        "fb_user_access_token": user_token,
        "fb_pages": pages,
        "fb_token_expires_at": expires_at,
    }

    # Update both business 6ace0304f758f9fdedd86b1c and 6ace0e973f210a92b8728bae
    for bid in ["6ace0304f758f9fdedd86b1c", "6ace0e973f210a92b8728bae"]:
        res = await db['businesses'].update_one({"_id": ObjectId(bid)}, {"$set": update_data})
        print(f"Updated business {bid}: matched={res.matched_count}, modified={res.modified_count}")

    # Also update user dy160080@gmail.com
    u = await db['users'].find_one({"email": "dy160080@gmail.com"})
    if u:
        res_u = await db['users'].update_one(
            {"_id": u["_id"]},
            {"$set": {
                "facebook_connected": True,
                "fb_page_id": page_id,
                "facebook_access_token": encrypt_token(user_token),
                "fb_page_access_token": encrypt_token(page_token),
            }}
        )
        print(f"Updated user {u['_id']}: matched={res_u.matched_count}, modified={res_u.modified_count}")

    close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(sync())
