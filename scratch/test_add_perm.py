import sys
sys.path.insert(0, ".")
import asyncio, httpx
from app.core.config import settings

async def f():
    app_id = settings.FACEBOOK_APP_ID
    app_secret = settings.FACEBOOK_APP_SECRET
    app_token = f"{app_id}|{app_secret}"

    async with httpx.AsyncClient() as c:
        # Check if we can add permission to app
        r = await c.post(
            f"https://graph.facebook.com/v19.0/{app_id}/permissions",
            params={"permission": "pages_manage_posts", "access_token": app_token}
        )
        print("POST /app/permissions status:", r.status_code, r.text)

if __name__ == "__main__":
    asyncio.run(f())
