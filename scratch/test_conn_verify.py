import sys
sys.path.insert(0, ".")
import asyncio
from app.core.database import connect_to_mongo, get_database, close_mongo_connection
from app.services.facebook_service import FacebookService

async def test():
    connect_to_mongo()
    db = get_database()
    conn = await FacebookService.get_connection(db, "6acaa95753963958eab2d632")
    print("get_connection:", conn)
    
    ver = await FacebookService.verify_page_token_permissions(db, "6acaa95753963958eab2d632")
    print("verify_permissions:", ver)
    close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(test())
