import sys
sys.path.insert(0, ".")
import asyncio
from bson import ObjectId
from app.core.database import connect_to_mongo, get_database, close_mongo_connection

async def f():
    connect_to_mongo()
    db = get_database()
    for bid in ["6ace0304f758f9fdedd86b1c", "6ace05ca1e06924210923576"]:
        b = await db['businesses'].find_one({"_id": ObjectId(bid)})
        print(f"\nBusiness {bid}:")
        if b:
            for k, v in b.items():
                print(f"  {k}: {str(v)[:100]}")
    
    c = await db['contents'].find_one({"_id": ObjectId("6ace05dc6cc81b1928dc0bc5")})
    print(f"\nContent 6ace05dc6cc81b1928dc0bc5:")
    if c:
        for k, v in c.items():
            print(f"  {k}: {str(v)[:100]}")
    close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(f())
