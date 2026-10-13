import sys
sys.path.insert(0, ".")
import asyncio
from app.core.database import connect_to_mongo, get_database, close_mongo_connection
from app.services.social_service import SocialService

async def test():
    connect_to_mongo()
    db = get_database()
    
    try:
        res = await SocialService.publish_to_facebook(
            db=db,
            business_id="6ace0304f758f9fdedd86b1c",
            content_id="6ace05dc6cc81b1928dc0bc5",
        )
        print("Publish success:", res)
    except Exception as e:
        print("Publish failed with:", type(e), getattr(e, "detail", str(e)))

    close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(test())
