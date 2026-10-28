import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone
from bson import ObjectId

from app.main import app
from app.core.database import get_database, connect_to_mongo
from app.core.security import create_access_token

pytestmark = pytest.mark.asyncio

TEST_PHONE_1 = "+919876543210"  # Developer test number in fast-path
TEST_PHONE_2 = "+919999999999"  # Second test user for isolation test


@pytest.fixture(autouse=True)
async def cleanup_database():
    connect_to_mongo()
    db = get_database()

    # Clean up test users before and after test
    phones = [TEST_PHONE_1, TEST_PHONE_2]
    user_docs = await db["users"].find({"phone_number": {"$in": phones}}).to_list(100)
    user_ids = [str(u["_id"]) for u in user_docs]

    if user_ids:
        await db["businesses"].delete_many({"$or": [{"owner_id": {"$in": user_ids}}, {"ownerId": {"$in": user_ids}}]})
        await db["brand_kits"].delete_many({"$or": [{"owner_id": {"$in": user_ids}}, {"user_id": {"$in": user_ids}}]})
        await db["subscriptions"].delete_many({"user_id": {"$in": user_ids}})
        await db["contents"].delete_many({"user_id": {"$in": user_ids}})
        await db["platform_onboarding_jobs"].delete_many({"user_id": {"$in": user_ids}})
        await db["website_analysis_jobs"].delete_many({"user_id": {"$in": user_ids}})
        await db["google_maps_onboarding_jobs"].delete_many({"user_id": {"$in": user_ids}})

    await db["users"].delete_many({"phone_number": {"$in": phones}})
    await db["pending_users"].delete_many({"phone_number": {"$in": phones}})
    await db["otps"].delete_many({"phone_number": {"$in": phones}})

    yield db

    # Post-test cleanup
    user_docs = await db["users"].find({"phone_number": {"$in": phones}}).to_list(100)
    user_ids = [str(u["_id"]) for u in user_docs]
    if user_ids:
        await db["businesses"].delete_many({"$or": [{"owner_id": {"$in": user_ids}}, {"ownerId": {"$in": user_ids}}]})
        await db["brand_kits"].delete_many({"$or": [{"owner_id": {"$in": user_ids}}, {"user_id": {"$in": user_ids}}]})
        await db["subscriptions"].delete_many({"user_id": {"$in": user_ids}})
        await db["contents"].delete_many({"user_id": {"$in": user_ids}})
    await db["users"].delete_many({"phone_number": {"$in": phones}})
    await db["pending_users"].delete_many({"phone_number": {"$in": phones}})


async def test_end_to_end_database_persistence_all_steps(cleanup_database):
    """
    Mandatory 15-step end-to-end database persistence verification:
    1. Mobile auth / OTP login
    2. User record in canonical 'users' collection
    3. Role selection ('businessman')
    4. Get Started / Onboarding status
    5. Multiple business services selection
    6. Business source selection (website)
    7. Business details saved and verified in DB
    8. Auto-fetched details persistence
    9. Brand Kit fields save and retrieval
    10. Subscription and social options
    11. Complete remaining onboarding steps
    12. Refresh and re-login
    13. Verify all saved values restored
    14. Update field and verify persistence
    15. Verify user isolation between User 1 and User 2
    """
    db = cleanup_database
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # =====================================================================
        # Step 1: User enters mobile number and completes authentication
        # =====================================================================
        # Request OTP
        send_res = await client.post("/api/v1/auth/send-otp", json={
            "phone_number": TEST_PHONE_1,
            "channel": "sms"
        })
        assert send_res.status_code == 200, f"send-otp failed: {send_res.text}"

        # Verify OTP (test developer bypass code 123456)
        verify_res = await client.post("/api/v1/auth/verify-otp", json={
            "phone_number": TEST_PHONE_1,
            "otp": "123456"
        })
        assert verify_res.status_code == 200, f"verify-otp failed: {verify_res.text}"
        auth_data = verify_res.json()
        token_1 = auth_data["access_token"]
        user_1_id = auth_data["user"]["id"]
        headers_1 = {"Authorization": f"Bearer {token_1}"}

        # =====================================================================
        # Step 2: User record exists in the intended database collection ('users')
        # =====================================================================
        user_in_db = await db["users"].find_one({"phone_number": TEST_PHONE_1})
        assert user_in_db is not None, "User record was not created in MongoDB 'users' collection!"
        assert str(user_in_db["_id"]) == user_1_id
        assert user_in_db.get("phone_verified") is True
        assert user_in_db.get("onboardingCompleted") is False
        assert user_in_db.get("onboarding_step") == 1

        # =====================================================================
        # Step 3: User selects a role ('businessman')
        # =====================================================================
        role_res = await client.patch("/api/v1/users/me", json={
            "role": "businessman"
        }, headers=headers_1)
        assert role_res.status_code == 200, f"Role selection failed: {role_res.text}"

        # Verify directly in MongoDB 'users' collection
        user_after_role = await db["users"].find_one({"_id": ObjectId(user_1_id)})
        assert user_after_role["role"] == "businessman", "Role was not persisted to 'users' collection!"

        # =====================================================================
        # Step 4: Progress through Get Started / check onboarding status
        # =====================================================================
        status_res = await client.get("/api/v1/onboarding/status", headers=headers_1)
        assert status_res.status_code == 200, f"onboarding/status failed: {status_res.text}"
        status_data = status_res.json()
        assert status_data["role"] == "businessman"
        assert status_data["onboarding_step"] in [1, 2]
        assert status_data["can_access_dashboard"] is False

        # =====================================================================
        # Step 5: User selects multiple business services
        # =====================================================================
        chosen_services = ["automate_social_media", "marketing_video", "leads_crm"]
        services_res = await client.post("/api/v1/onboarding/services", json={
            "selected_services": chosen_services
        }, headers=headers_1)
        assert services_res.status_code == 200, f"Saving services failed: {services_res.text}"

        # Verify persistence in both 'users' and 'businesses' collections
        user_after_services = await db["users"].find_one({"_id": ObjectId(user_1_id)})
        assert user_after_services.get("selected_services") == chosen_services, "Services not saved in 'users'!"

        biz_after_services = await db["businesses"].find_one({
            "$or": [{"owner_id": user_1_id}, {"ownerId": user_1_id}]
        })
        assert biz_after_services is not None, "Business doc not created/updated for services!"
        assert biz_after_services.get("owner_id") == user_1_id, "Business doc missing owner_id!"
        assert biz_after_services.get("selected_services") == chosen_services, "Services not saved in 'businesses'!"

        # =====================================================================
        # Step 6: User chooses a business source (website)
        # =====================================================================
        presence_res = await client.post("/api/v1/onboarding/online-presence", json={
            "online_presence": "website",
            "business_name": "Sharma Electronics",
            "category": "Retail",
            "website": "https://sharmaelectronics.in"
        }, headers=headers_1)
        assert presence_res.status_code == 200, f"online-presence failed: {presence_res.text}"

        # Verify in 'users' and 'businesses' collections
        user_after_presence = await db["users"].find_one({"_id": ObjectId(user_1_id)})
        assert user_after_presence.get("online_presence") == "website", "online_presence not saved in 'users'!"
        assert user_after_presence.get("onboarding_step") >= 2

        biz_after_presence = await db["businesses"].find_one({
            "$or": [{"owner_id": user_1_id}, {"ownerId": user_1_id}]
        })
        assert biz_after_presence is not None
        assert biz_after_presence.get("owner_id") == user_1_id
        assert biz_after_presence.get("online_presence") == "website"
        assert biz_after_presence.get("business_name") == "Sharma Electronics"

        # =====================================================================
        # Step 7 & 8: Available business details are fetched and saved
        # =====================================================================
        # Save business details into business profile
        biz_update_res = await client.put("/api/v1/businesses/me", json={
            "business_name": "Sharma Electronics Pvt Ltd",
            "tagline": "Trusted Tech Since 1998",
            "city": "Jaipur",
            "website": "https://sharmaelectronics.in",
            "description": "Leading electronics store in Jaipur offering top brands."
        }, headers=headers_1)
        assert biz_update_res.status_code == 200, f"Business update failed: {biz_update_res.text}"

        # Verify in database
        biz_doc_updated = await db["businesses"].find_one({
            "$or": [{"owner_id": user_1_id}, {"ownerId": user_1_id}]
        })
        assert biz_doc_updated["tagline"] == "Trusted Tech Since 1998"
        assert biz_doc_updated["city"] == "Jaipur"
        assert biz_doc_updated["owner_id"] == user_1_id

        # =====================================================================
        # Step 9: User completes Brand Kit fields
        # =====================================================================
        brand_kit_payload = {
            "business_name": "Sharma Electronics Pvt Ltd",
            "tagline": "Trusted Tech Since 1998",
            "primary_color": "#0D47A1",
            "secondary_color": "#1976D2",
            "accent_color": "#FFC107",
            "brand_colors": ["#0D47A1", "#1976D2", "#FFC107"],
            "city": "Jaipur",
            "language": "Hindi, English",
            "tones": ["Professional", "Trustworthy"],
            "target_audience": "Families and tech enthusiasts",
            "is_draft": False
        }
        brand_save_res = await client.post("/api/v1/brand-kit", json=brand_kit_payload, headers=headers_1)
        assert brand_save_res.status_code in [200, 201], f"Brand Kit save failed: {brand_save_res.text}"

        # Verify Brand Kit exists in MongoDB 'brand_kits' collection
        brand_in_db = await db["brand_kits"].find_one({
            "$or": [{"owner_id": user_1_id}, {"user_id": user_1_id}]
        })
        assert brand_in_db is not None, "Brand Kit document was not persisted to 'brand_kits' collection!"
        assert brand_in_db["owner_id"] == user_1_id
        assert brand_in_db["primary_color"] == "#0D47A1"
        assert brand_in_db["tagline"] == "Trusted Tech Since 1998"

        # Verify GET /api/v1/brand-kit/me retrieves the exact saved data
        brand_get_res = await client.get("/api/v1/brand-kit/me", headers=headers_1)
        assert brand_get_res.status_code == 200
        brand_fetched = brand_get_res.json()["data"]
        assert brand_fetched["primary_color"] == "#0D47A1"
        assert brand_fetched["tagline"] == "Trusted Tech Since 1998"

        # =====================================================================
        # Step 10: User views subscription and social connection options
        # =====================================================================
        # Subscription status
        sub_res = await client.get("/subscription/me", headers=headers_1)
        assert sub_res.status_code == 200
        sub_data = sub_res.json()["data"]
        assert sub_data["status"] == "active"
        assert sub_data["plan_id"] == "FREE"

        # Social connectivity options
        social_res = await client.get("/api/v1/social/onboarding-status", headers=headers_1)
        assert social_res.status_code == 200
        social_data = social_res.json()
        assert "platforms" in social_data
        assert "instagram" in social_data["platforms"]

        # =====================================================================
        # Step 11: User moves through remaining onboarding steps
        # =====================================================================
        progress_res = await client.patch("/api/v1/onboarding/progress", json={
            "social_connectivity_skipped": True,
            "plan_selection_skipped": True,
            "onboardingCompleted": True
        }, headers=headers_1)
        assert progress_res.status_code == 200, f"Progress update failed: {progress_res.text}"

        # Verify user marked completed in 'users'
        user_after_complete = await db["users"].find_one({"_id": ObjectId(user_1_id)})
        assert user_after_complete.get("onboardingCompleted") is True, "onboardingCompleted not set to True in 'users'!"

        # =====================================================================
        # Step 12 & 13: Refresh the page and sign in again; verify restoration
        # =====================================================================
        # Re-authenticate to simulate fresh session
        re_login_res = await client.post("/api/v1/auth/verify-otp", json={
            "phone_number": TEST_PHONE_1,
            "otp": "123456"
        })
        assert re_login_res.status_code == 200
        new_token = re_login_res.json()["access_token"]
        new_headers = {"Authorization": f"Bearer {new_token}"}

        # Retrieve profile
        profile_res = await client.get("/api/v1/users/me", headers=new_headers)
        assert profile_res.status_code == 200
        profile = profile_res.json()["data"]
        assert profile["role"] == "businessman", "Restored profile lost role!"
        assert profile["selected_services"] == chosen_services, "Restored profile lost selected_services!"
        assert profile["phone_number"] == TEST_PHONE_1

        # Retrieve onboarding status
        re_status_res = await client.get("/api/v1/onboarding/status", headers=new_headers)
        assert re_status_res.status_code == 200
        re_status = re_status_res.json()
        assert re_status["onboarding_completed"] is True or re_status["onboardingCompleted"] is True
        assert re_status["selected_services"] == chosen_services
        assert re_status["online_presence"] == "website"

        # Retrieve business details
        re_biz_res = await client.get("/api/v1/businesses/me", headers=new_headers)
        assert re_biz_res.status_code == 200
        re_biz = re_biz_res.json()["data"]
        assert re_biz["city"] == "Jaipur"
        assert re_biz["tagline"] == "Trusted Tech Since 1998"

        # Retrieve Brand Kit
        re_brand_res = await client.get("/api/v1/brand-kit/me", headers=new_headers)
        assert re_brand_res.status_code == 200
        re_brand = re_brand_res.json()["data"]
        assert re_brand["primary_color"] == "#0D47A1"
        assert re_brand["tagline"] == "Trusted Tech Since 1998"

        # =====================================================================
        # Step 14: Update a field and verify change persists
        # =====================================================================
        update_field_res = await client.put("/api/v1/brand-kit", json={
            "tagline": "Smart Electronics for Modern India",
            "business_name": "Sharma Electronics Pvt Ltd"
        }, headers=new_headers)
        assert update_field_res.status_code == 200, f"Field update failed: {update_field_res.text}"

        # Verify change in database
        brand_after_field_update = await db["brand_kits"].find_one({
            "$or": [{"owner_id": user_1_id}, {"user_id": user_1_id}]
        })
        assert brand_after_field_update["tagline"] == "Smart Electronics for Modern India", "Updated field did not persist!"

        # Verify change via GET endpoint
        get_after_update = await client.get("/api/v1/brand-kit/me", headers=new_headers)
        assert get_after_update.json()["data"]["tagline"] == "Smart Electronics for Modern India"

        # =====================================================================
        # Step 15: Verify data isolation between users
        # =====================================================================
        # Authenticate User 2
        u2_send = await client.post("/api/v1/auth/send-otp", json={"phone_number": TEST_PHONE_2})
        assert u2_send.status_code == 200
        u2_verify = await client.post("/api/v1/auth/verify-otp", json={
            "phone_number": TEST_PHONE_2,
            "otp": "123456"
        })
        assert u2_verify.status_code == 200
        token_2 = u2_verify.json()["access_token"]
        user_2_id = u2_verify.json()["user"]["id"]
        headers_2 = {"Authorization": f"Bearer {token_2}"}

        assert user_1_id != user_2_id, "User 1 and User 2 must have distinct user IDs"

        # User 2 sets their role to businessman (required for Brand Kit management)
        u2_role_res = await client.patch("/api/v1/users/me", json={"role": "businessman"}, headers=headers_2)
        assert u2_role_res.status_code == 200

        # User 2 Brand Kit should NOT see User 1's Brand Kit
        u2_brand_res = await client.get("/api/v1/brand-kit/me", headers=headers_2)
        assert u2_brand_res.status_code == 200
        u2_brand_data = u2_brand_res.json()["data"]
        # User 2 has not set a tagline or custom colors
        if u2_brand_data:
            assert u2_brand_data.get("primary_color") != "#0D47A1", "Data leak! User 2 received User 1's brand color!"
            assert u2_brand_data.get("tagline") != "Smart Electronics for Modern India", "Data leak! User 2 received User 1's tagline!"

        # User 2 saves their own Brand Kit
        u2_save = await client.post("/api/v1/brand-kit", json={
            "business_name": "Verma Organic Farm",
            "tagline": "Pure and Natural",
            "primary_color": "#2E7D32",
            "is_draft": False
        }, headers=headers_2)
        assert u2_save.status_code in [200, 201]

        # Verify User 1's Brand Kit remains untouched in the database
        u1_brand_recheck = await db["brand_kits"].find_one({
            "$or": [{"owner_id": user_1_id}, {"user_id": user_1_id}]
        })
        assert u1_brand_recheck["primary_color"] == "#0D47A1", "User 1 data was overwritten by User 2!"
        assert u1_brand_recheck["tagline"] == "Smart Electronics for Modern India"

        # Verify User 2's Brand Kit in database
        u2_brand_in_db = await db["brand_kits"].find_one({
            "$or": [{"owner_id": user_2_id}, {"user_id": user_2_id}]
        })
        assert u2_brand_in_db["primary_color"] == "#2E7D32"
        assert u2_brand_in_db["tagline"] == "Pure and Natural"
        assert u2_brand_in_db["owner_id"] == user_2_id
