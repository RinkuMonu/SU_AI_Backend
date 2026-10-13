import sys
sys.path.insert(0, ".")
import asyncio
from app.core.database import connect_to_mongo, get_database, close_mongo_connection

async def f():
    connect_to_mongo()
    db = get_database()
    print("--- LATEST 10 BUSINESSES ---")
    async for b in db['businesses'].find().sort('_id', -1).limit(10):
        print(f"_id={b.get('_id')} updated={b.get('updated_at')} name={b.get('name')} email={b.get('email')} page_id={b.get('fb_page_id')} userId={b.get('userId')} user_id={b.get('user_id')} owner_id={b.get('owner_id')}")

    print("\n--- USERS WITH FB CONNECTED ---")
    async for u in db['users'].find({"fb_page_id": {"$exists": True}}):
        print(f"User: id={u.get('_id')} email={u.get('email')} fb_page_id={u.get('fb_page_id')} fb_conn={u.get('facebook_connected')}")

    close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(f())
