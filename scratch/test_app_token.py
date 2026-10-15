import sys
sys.path.insert(0, ".")
import asyncio
import httpx
from app.core.config import settings

async def test_meta():
    app_id = settings.FACEBOOK_APP_ID
    app_secret = settings.FACEBOOK_APP_SECRET
    app_token = f"{app_id}|{app_secret}"
    page_id = "627610063778275"
    user_id = "122230211864563814"

    async with httpx.AsyncClient() as client:
        # 1. Check page access via app token
        res_page = await client.get(
            f"https://graph.facebook.com/v19.0/{page_id}?fields=id,name,access_token,is_published&access_token={app_token}"
        )
        print("Page via app token:", res_page.status_code, res_page.json())

        # 2. Check app subscriptions / webhooks
        res_sub = await client.get(
            f"https://graph.facebook.com/v19.0/{app_id}/subscriptions?access_token={app_token}"
        )
        print("App subscriptions:", res_sub.status_code, res_sub.json())

        # 3. Check what happens if app tries to post to page directly with app_token
        res_post_app = await client.post(
            f"https://graph.facebook.com/v19.0/{page_id}/feed",
            params={"message": "Test from app token", "access_token": app_token}
        )
        print("Feed post via app token:", res_post_app.status_code, res_post_app.json())

if __name__ == "__main__":
    asyncio.run(test_meta())
