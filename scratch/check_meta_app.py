import sys
sys.path.insert(0, ".")
import asyncio
import httpx
from app.core.config import settings

async def check_app():
    app_id = settings.FACEBOOK_APP_ID
    app_secret = settings.FACEBOOK_APP_SECRET
    app_token = f"{app_id}|{app_secret}"

    async with httpx.AsyncClient() as client:
        # App details
        res = await client.get(
            f"https://graph.facebook.com/v19.0/{app_id}?fields=id,name,category,link,roles&access_token={app_token}"
        )
        print("App details:", res.status_code, res.json())

        # Roles on App
        roles_res = await client.get(
            f"https://graph.facebook.com/v19.0/{app_id}/roles?access_token={app_token}"
        )
        print("App roles:", roles_res.status_code, roles_res.json())

        # Permissions on App
        perms_res = await client.get(
            f"https://graph.facebook.com/v19.0/{app_id}/permissions?access_token={app_token}"
        )
        print("App permissions:", perms_res.status_code, perms_res.json())

if __name__ == "__main__":
    asyncio.run(check_app())
