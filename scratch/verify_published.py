import sys
sys.path.insert(0, ".")
import asyncio
from bson import ObjectId
from app.core.database import connect_to_mongo, get_database, close_mongo_connection

async def f():
    connect_to_mongo()
    db = get_database()
    c = await db['contents'].find_one({'_id': ObjectId('6ace05dc6cc81b1928dc0bc5')})
    if c:
        print("Status:", c.get('status'))
        print("Post ID:", c.get('fb_post_id'))
        print("Published at:", c.get('published_at'))
        print("Platform:", c.get('platform'))
    close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(f())
