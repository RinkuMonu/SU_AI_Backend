import sys
sys.path.insert(0, ".")
import asyncio
from bson import ObjectId
from app.core.database import connect_to_mongo, get_database, close_mongo_connection

async def f():
    connect_to_mongo()
    db = get_database()
    b = await db['businesses'].find_one({'owner_id': {'$exists': True}})
    if b:
        print("owner_id:", type(b['owner_id']), repr(b['owner_id']))
    
    # Check user dy160080@gmail.com
    u = await db['users'].find_one({'email': 'dy160080@gmail.com'})
    if u:
        uid_str = str(u['_id'])
        print("Found user:", uid_str)
        # Search businesses with string vs ObjectId
        b_str = await db['businesses'].find_one({"owner_id": uid_str})
        b_oid = await db['businesses'].find_one({"owner_id": ObjectId(uid_str)})
        print("b_str:", b_str.get('_id') if b_str else None)
        print("b_oid:", b_oid.get('_id') if b_oid else None)

    close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(f())
