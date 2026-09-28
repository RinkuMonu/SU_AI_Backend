import asyncio
from app.core.database import connect_to_mongo, close_mongo_connection
from app.services.website_builder_service import WebsiteBuilderService

async def main():
    connect_to_mongo()
    coll = await WebsiteBuilderService.get_project_collection()
    docs = await coll.find().sort("_id", -1).limit(1).to_list(1)
    if docs:
        print("Project exists:", docs[0]["_id"])
        print("Pages count:", len(docs[0].get("pages", [])))
        print("Theme:", docs[0].get("theme"))
    else:
        print("No projects found.")
    
    sess_coll = await WebsiteBuilderService.get_session_collection()
    sess_docs = await sess_coll.find().sort("_id", -1).limit(1).to_list(1)
    if sess_docs:
        print("Session exists:", sess_docs[0]["_id"])
        print("Session project ID:", sess_docs[0].get("website_project_id"))
    else:
        print("No sessions found.")

if __name__ == "__main__":
    asyncio.run(main())
