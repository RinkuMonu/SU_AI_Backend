import sys
sys.path.insert(0, ".")
import asyncio, httpx
from app.core.config import settings

async def f():
    app_id = settings.FACEBOOK_APP_ID
    app_secret = settings.FACEBOOK_APP_SECRET
    app_token = f"{app_id}|{app_secret}"

    async with httpx.AsyncClient() as c:
        # Check app info
        r = await c.get(f"https://graph.facebook.com/v19.0/{app_id}?access_token={app_token}")
        print("App:", r.json())

        # Check app features
        r_feat = await c.get(f"https://graph.facebook.com/v19.0/{app_id}/app_features?access_token={app_token}")
        print("Features status:", r_feat.status_code, r_feat.json())

if __name__ == "__main__":
    asyncio.run(f())
