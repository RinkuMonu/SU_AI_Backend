import asyncio
from app.core.database import connect_to_mongo, get_database

async def check():
    connect_to_mongo()
    db = get_database()
    u = await db["users"].find_one({"email": "sejalgupta1838@gmail.com"})
    print("User found:", bool(u))
    if u:
        print("Email:", u.get("email"))
        print("Verified:", u.get("emailVerified"))
        print("Role:", u.get("role"))

if __name__ == "__main__":
    asyncio.run(check())
