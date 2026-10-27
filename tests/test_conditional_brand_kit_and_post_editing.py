import asyncio
from datetime import datetime, timezone
import pytest
from bson import ObjectId
from unittest.mock import patch, MagicMock
from fastapi import HTTPException

from app.services.brand_service import (
    get_onboarding_status,
    save_brand_kit_submission,
    validate_required_brand_kit_fields,
    calculate_brand_kit_completion,
)
from app.api.endpoints.onboarding import get_onboarding_status as get_onboarding_progress_endpoint
from app.api.endpoints.content import get_single_content, save_content, delete_content
from app.services.social_connectivity_service import get_social_onboarding_status
from app.services.plan_onboarding_service import PlanOnboardingService


# ==============================================================================
# In-Memory Mock Database
# ==============================================================================

class MockAsyncCursor:
    def __init__(self, docs):
        self.docs = list(docs)
        self.index = 0

    def sort(self, key, direction=1):
        # Optional sorting support
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index < len(self.docs):
            doc = self.docs[self.index]
            self.index += 1
            return dict(doc)
        raise StopAsyncIteration

    async def to_list(self, length=None):
        if length is not None:
            return [dict(d) for d in self.docs[:length]]
        return [dict(d) for d in self.docs]


class MockCollection:
    def __init__(self, name):
        self.name = name
        self.docs = []

    def _matches(self, doc, query):
        if not query:
            return True
        for k, v in query.items():
            if k == "$or":
                if not any(self._matches(doc, subq) for subq in v):
                    return False
            elif k == "$and":
                if not all(self._matches(doc, subq) for subq in v):
                    return False
            else:
                doc_val = doc.get(k)
                if isinstance(v, dict):
                    if "$exists" in v:
                        exists = k in doc and doc[k] is not None
                        if exists != v["$exists"]:
                            return False
                    elif "$in" in v:
                        if doc_val not in v["$in"]:
                            return False
                else:
                    if str(doc_val) != str(v) and doc_val != v:
                        return False
        return True

    async def find_one(self, query):
        for d in self.docs:
            if self._matches(d, query):
                return dict(d)
        return None

    def find(self, query=None):
        matched = [dict(d) for d in self.docs if self._matches(d, query or {})]
        return MockAsyncCursor(matched)

    async def insert_one(self, doc):
        d = dict(doc)
        if "_id" not in d:
            d["_id"] = ObjectId()
        self.docs.append(d)
        res = MagicMock()
        res.inserted_id = d["_id"]
        return res

    async def update_one(self, query, update, upsert=False):
        for idx, d in enumerate(self.docs):
            if self._matches(d, query):
                if "$set" in update:
                    d.update(update["$set"])
                if "$unset" in update:
                    for uk in update["$unset"]:
                        d.pop(uk, None)
                self.docs[idx] = d
                res = MagicMock()
                res.modified_count = 1
                res.upserted_id = None
                return res

        if upsert:
            new_doc = {}
            for qk, qv in query.items():
                if not qk.startswith("$"):
                    new_doc[qk] = qv
            if "$set" in update:
                new_doc.update(update["$set"])
            if "$setOnInsert" in update:
                new_doc.update(update["$setOnInsert"])
            if "_id" not in new_doc:
                new_doc["_id"] = ObjectId()
            self.docs.append(new_doc)
            res = MagicMock()
            res.modified_count = 0
            res.upserted_id = new_doc["_id"]
            return res

        res = MagicMock()
        res.modified_count = 0
        res.upserted_id = None
        return res

    async def find_one_and_update(self, query, update, upsert=False, return_document=None):
        for idx, d in enumerate(self.docs):
            if self._matches(d, query):
                if "$set" in update:
                    d.update(update["$set"])
                self.docs[idx] = d
                return dict(d)
        if upsert:
            new_doc = {}
            for qk, qv in query.items():
                if not qk.startswith("$"):
                    new_doc[qk] = qv
            if "$set" in update:
                new_doc.update(update["$set"])
            if "$setOnInsert" in update:
                new_doc.update(update["$setOnInsert"])
            if "_id" not in new_doc:
                new_doc["_id"] = ObjectId()
            self.docs.append(new_doc)
            return dict(new_doc)
        return None

    async def delete_one(self, query):
        for idx, d in enumerate(self.docs):
            if self._matches(d, query):
                self.docs.pop(idx)
                res = MagicMock()
                res.deleted_count = 1
                return res
        res = MagicMock()
        res.deleted_count = 0
        return res

    async def count_documents(self, query):
        count = sum(1 for d in self.docs if self._matches(d, query))
        return count


class MockDatabase:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = MockCollection(name)
        return self.collections[name]

    def __getattr__(self, name):
        return self[name]


# ==============================================================================
# Test Cases (1 through 7)
# ==============================================================================

@pytest.mark.asyncio
async def test_case_1_no_online_presence_incomplete_brand_kit():
    """
    Case 1: No online presence + incomplete Brand Kit:
    - Completion is applicable.
    - Required fields are checked and determined incomplete.
    - Status is returned correctly so frontend can display optional completion popup.
    - Completion is optional: it does not block onboarding progress.
    """
    db = MockDatabase()
    user_id = str(ObjectId())
    user_doc = {
        "_id": ObjectId(user_id),
        "id": user_id,
        "name": "Test Merchant",
        "email": "merchant@test.com",
        "role": "businessman",
        "online_presence": "no_online_presence",
        "onboarding_step": 1,
        "onboardingCompleted": False
    }
    await db["users"].insert_one(user_doc)
    await db["businesses"].insert_one({
        "_id": ObjectId(),
        "owner_id": user_id,
        "name": "My Offline Shop",
        "online_presence": "no_online_presence",
    })

    # Incomplete Brand Kit (missing required logo_url, secondary_color, etc.)
    await db["brand_kits"].insert_one({
        "_id": ObjectId(),
        "owner_id": user_id,
        "business_name": "My Offline Shop",
        "primary_color": "#FF5733",
        "brand_kit_status": "in_progress",
        "brand_kit_completed": False,
        "brand_kit_dismissed": False,
    })

    current_user = dict(user_doc)
    brand_status = await get_onboarding_status(db, current_user)

    assert brand_status.role == "businessman"
    assert brand_status.brand_kit_completed is False
    assert brand_status.should_show_modal is True
    assert "visual_identity" in brand_status.pending_sections or "business_identity" in brand_status.pending_sections

    # Check onboarding endpoint does not block and reflects optional completion popup
    with patch("app.api.endpoints.onboarding.get_database", return_value=db), \
         patch("app.api.endpoints.onboarding.BusinessService.get_business_by_owner", return_value=None):
        progress = await get_onboarding_progress_endpoint(current_user=current_user)
        step1 = progress["steps"]["step_1_brand_kit"]
        assert step1["is_applicable"] is True
        assert step1["is_completed"] is False
        assert step1["should_show_modal"] is True
        assert progress["current_modal_to_show"] == "brand_kit"
        # Can still access dashboard or proceed
        assert "steps" in progress


@pytest.mark.asyncio
async def test_case_2_no_online_presence_completed_brand_kit():
    """
    Case 2: No online presence + completed Brand Kit:
    - All required fields are present.
    - brand_kit_completed is True.
    - should_show_modal is False (no unnecessary completion prompt is shown).
    """
    db = MockDatabase()
    user_id = str(ObjectId())
    user_doc = {
        "_id": ObjectId(user_id),
        "id": user_id,
        "name": "Complete Merchant",
        "email": "complete@test.com",
        "role": "businessman",
        "online_presence": "no_online_presence",
    }
    await db["users"].insert_one(user_doc)
    await db["businesses"].insert_one({
        "_id": ObjectId(),
        "owner_id": user_id,
        "name": "Complete Shop",
        "online_presence": "no_online_presence",
    })

    # Fully populated Brand Kit
    full_brand_data = {
        "_id": ObjectId(),
        "owner_id": user_id,
        "business_name": "Complete Shop",
        "brand_name": "Complete Shop",
        "business_category": "Retail",
        "logo_url": "https://example.com/logo.png",
        "primary_color": "#111111",
        "secondary_color": "#222222",
        "accent_color": "#333333",
        "font": "Inter",
        "age_group": "25-34",
        "customer_type": "Direct Consumers",
        "location_focus": "Mumbai",
        "brand_kit_status": "completed",
        "brand_kit_completed": True,
        "brand_kit_dismissed": False,
    }
    await db["brand_kits"].insert_one(full_brand_data)

    current_user = dict(user_doc)
    brand_status = await get_onboarding_status(db, current_user)

    assert brand_status.brand_kit_completed is True
    assert brand_status.should_show_modal is False
    assert brand_status.brand_kit_status == "completed"

    with patch("app.api.endpoints.onboarding.get_database", return_value=db), \
         patch("app.api.endpoints.onboarding.BusinessService.get_business_by_owner", return_value=None):
        progress = await get_onboarding_progress_endpoint(current_user=current_user)
        step1 = progress["steps"]["step_1_brand_kit"]
        assert step1["is_completed"] is True
        assert step1["should_show_modal"] is False
        assert progress["current_modal_to_show"] != "brand_kit"


@pytest.mark.asyncio
@pytest.mark.parametrize("presence_source", [
    "website",
    "google_maps",
    "marketplace_seller",
    "wholesale_b2b"
])
async def test_case_3_non_no_presence_sources_do_not_require_brand_kit(presence_source):
    """
    Case 3: Website, Google Maps, Marketplace seller, and Wholesale/B2B:
    - Do not require Brand Kit completion to proceed through onboarding or post generation.
    - Keeps source-specific business data and Brand Kit data distinct (does not infer Brand Kit is complete).
    - should_show_modal is False.
    """
    db = MockDatabase()
    user_id = str(ObjectId())
    user_doc = {
        "_id": ObjectId(user_id),
        "id": user_id,
        "name": f"{presence_source} User",
        "email": f"{presence_source}@test.com",
        "role": "businessman",
        "online_presence": presence_source,
    }
    await db["users"].insert_one(user_doc)
    await db["businesses"].insert_one({
        "_id": ObjectId(),
        "owner_id": user_id,
        "name": f"Online Business {presence_source}",
        "online_presence": presence_source,
        "website_url": "https://example.com" if presence_source == "website" else None,
        "google_maps_place_id": "ChIJ123" if presence_source == "google_maps" else None,
    })

    # Note: No document exists in brand_kits
    current_user = dict(user_doc)
    brand_status = await get_onboarding_status(db, current_user)

    # Distinct check: Brand Kit is NOT marked complete simply because a website or maps exists
    assert brand_status.brand_kit_completed is False
    assert brand_status.brand_kit is None
    # Modal must NOT be shown for these sources
    assert brand_status.should_show_modal is False

    # Check onboarding endpoint
    with patch("app.api.endpoints.onboarding.get_database", return_value=db), \
         patch("app.api.endpoints.onboarding.BusinessService.get_business_by_owner", return_value=None):
        progress = await get_onboarding_progress_endpoint(current_user=current_user)
        step1 = progress["steps"]["step_1_brand_kit"]
        assert step1["is_applicable"] is False
        assert step1["status"] == "not_applicable"
        assert step1["should_show_modal"] is False
        assert progress["current_modal_to_show"] != "brand_kit"

    # Social connectivity check: Brand Kit is NOT blocking, and status remains distinct
    social_status = await get_social_onboarding_status(db, current_user)
    assert social_status.brand_kit_completed is False  # Distinct data maintained
    assert social_status.should_show_modal is True      # Eligible to connect social accounts directly


@pytest.mark.asyncio
async def test_case_4_generated_unlocked_post_fetch_and_edit_by_owner():
    """
    Case 4: A generated unlocked post can be fetched and edited by its owner.
    - Returns existing generated image, caption, hashtags, content type, etc. to prepopulate editor.
    - Edits are saved in place against the correct post without creating duplicates.
    """
    db = MockDatabase()
    user_id = str(ObjectId())
    user_doc = {"_id": ObjectId(user_id), "id": user_id, "name": "Owner User"}
    await db["users"].insert_one(user_doc)

    biz_id = str(ObjectId())
    mock_biz = MagicMock()
    mock_biz.id = ObjectId(biz_id)
    mock_biz.owner_id = user_id
    await db["businesses"].insert_one({"_id": ObjectId(biz_id), "owner_id": user_id, "name": "Owner Biz"})

    post_id = str(ObjectId())
    initial_post = {
        "_id": ObjectId(post_id),
        "user_id": user_id,
        "business_id": biz_id,
        "content_type": "post",
        "caption": "Initial catchy caption #startup",
        "primary_text": "Initial catchy caption #startup",
        "image_url": "https://storage.example.com/generated_1.jpg",
        "media_url": "https://storage.example.com/generated_1.jpg",
        "hashtags": ["#startup", "#growth"],
        "headline": "Grow Your Business",
        "is_locked": False,
        "platform": "instagram",
        "created_at": datetime.now(timezone.utc),
    }
    await db["contents"].insert_one(initial_post)

    with patch("app.api.endpoints.content.get_database", return_value=db), \
         patch("app.api.endpoints.content.BusinessService.get_business_by_owner", return_value=mock_biz):
        
        # 1. Fetch post for editing
        fetch_res = await get_single_content(content_id=post_id, current_user=user_doc)
        assert fetch_res["success"] is True
        data = fetch_res["data"]
        assert data["id"] == post_id
        assert data["caption"] == "Initial catchy caption #startup"
        assert data["image_url"] == "https://storage.example.com/generated_1.jpg"
        assert data["hashtags"] == ["#startup", "#growth"]
        assert data["content_type"] == "post"

        # 2. Edit post via PUT /api/v1/content/update (or with content_id)
        edit_payload = {
            "id": post_id,
            "caption": "Updated refined caption #viral",
            "hashtags": ["#viral", "#success"],
            "headline": "Elevate Your Brand"
        }
        update_res = await save_content(content=edit_payload, content_id=None, current_user=user_doc)
        assert update_res["success"] is True
        assert update_res["message"] == "Post updated successfully"
        assert update_res["data"]["caption"] == "Updated refined caption #viral"

        # Verify no duplicate post was created
        all_posts = await db["contents"].count_documents({"user_id": user_id})
        assert all_posts == 1

        # Check DB reflects updated values
        saved = await db["contents"].find_one({"_id": ObjectId(post_id)})
        assert saved["caption"] == "Updated refined caption #viral"
        assert saved["hashtags"] == ["#viral", "#success"]
        assert saved["image_url"] == "https://storage.example.com/generated_1.jpg"


@pytest.mark.asyncio
async def test_case_5_locked_posts_protected_by_entitlement_rules():
    """
    Case 5: Locked posts remain protected by entitlement rules:
    - Free user cannot fetch or edit a locked post (raises HTTP 403).
    - Paid user (e.g. STARTER / PRO) can fetch and edit a locked post.
    """
    db = MockDatabase()
    owner_id = str(ObjectId())
    user_doc = {"_id": ObjectId(owner_id), "id": owner_id, "name": "Entitlement User"}
    await db["users"].insert_one(user_doc)

    biz_id = str(ObjectId())
    mock_biz = MagicMock()
    mock_biz.id = ObjectId(biz_id)
    mock_biz.owner_id = owner_id
    await db["businesses"].insert_one({"_id": ObjectId(biz_id), "owner_id": owner_id, "name": "Entitlement Biz"})

    post_id = str(ObjectId())
    locked_post = {
        "_id": ObjectId(post_id),
        "user_id": owner_id,
        "business_id": biz_id,
        "content_type": "post",
        "caption": "Exclusive locked creative post",
        "image_url": "https://storage.example.com/locked.jpg",
        "is_locked": True,
    }
    await db["contents"].insert_one(locked_post)

    # Free plan subscription
    await db["subscriptions"].insert_one({
        "user_id": owner_id,
        "plan_id": "FREE",
        "status": "active"
    })

    with patch("app.api.endpoints.content.get_database", return_value=db), \
         patch("app.api.endpoints.content.BusinessService.get_business_by_owner", return_value=mock_biz):

        # Attempt to fetch as Free user -> Expect 403 Forbidden
        with pytest.raises(HTTPException) as exc_fetch:
            await get_single_content(content_id=post_id, current_user=user_doc)
        assert exc_fetch.value.status_code == 403
        assert "locked" in exc_fetch.value.detail.lower()

        # Attempt to edit as Free user -> Expect 403 Forbidden
        with pytest.raises(HTTPException) as exc_edit:
            await save_content(
                content={"id": post_id, "caption": "Hacked free edit"},
                content_id=post_id,
                current_user=user_doc
            )
        assert exc_edit.value.status_code == 403
        assert "locked" in exc_edit.value.detail.lower()

        # Upgrade user to PRO plan
        await db["subscriptions"].update_one(
            {"user_id": owner_id},
            {"$set": {"plan_id": "PRO", "status": "active"}}
        )

        # Now fetch succeeds for paid user
        paid_fetch = await get_single_content(content_id=post_id, current_user=user_doc)
        assert paid_fetch["success"] is True
        assert paid_fetch["data"]["caption"] == "Exclusive locked creative post"

        # And edit succeeds for paid user
        paid_edit = await save_content(
            content={"id": post_id, "caption": "Legitimate Pro Edit"},
            content_id=post_id,
            current_user=user_doc
        )
        assert paid_edit["success"] is True
        assert paid_edit["data"]["caption"] == "Legitimate Pro Edit"


@pytest.mark.asyncio
async def test_case_6_unauthorized_users_cannot_read_or_modify_other_users_posts():
    """
    Case 6: Unauthorized users cannot read, modify, or delete another user's posts.
    - Returns HTTP 403 Forbidden for cross-user operations.
    """
    db = MockDatabase()
    user_a_id = str(ObjectId())
    user_b_id = str(ObjectId())

    user_a = {"_id": ObjectId(user_a_id), "id": user_a_id, "name": "User A"}
    user_b = {"_id": ObjectId(user_b_id), "id": user_b_id, "name": "User B"}

    await db["users"].insert_one(user_a)
    await db["users"].insert_one(user_b)

    biz_a_id = str(ObjectId())
    biz_b_id = str(ObjectId())

    mock_biz_b = MagicMock()
    mock_biz_b.id = ObjectId(biz_b_id)
    mock_biz_b.owner_id = user_b_id

    # Post belongs to User A
    post_a_id = str(ObjectId())
    await db["contents"].insert_one({
        "_id": ObjectId(post_a_id),
        "user_id": user_a_id,
        "business_id": biz_a_id,
        "caption": "Secret post of User A",
        "image_url": "https://example.com/user_a.png",
        "is_locked": False
    })

    with patch("app.api.endpoints.content.get_database", return_value=db), \
         patch("app.api.endpoints.content.BusinessService.get_business_by_owner", return_value=mock_biz_b):

        # 1. User B tries to GET User A's post
        with pytest.raises(HTTPException) as exc_get:
            await get_single_content(content_id=post_a_id, current_user=user_b)
        assert exc_get.value.status_code == 403
        assert "permission" in exc_get.value.detail.lower()

        # 2. User B tries to PUT / update User A's post
        with pytest.raises(HTTPException) as exc_put:
            await save_content(
                content={"id": post_a_id, "caption": "Defaced by User B"},
                content_id=post_a_id,
                current_user=user_b
            )
        assert exc_put.value.status_code == 403
        assert "permission" in exc_put.value.detail.lower()

        # 3. User B tries to DELETE User A's post
        with pytest.raises(HTTPException) as exc_del:
            await delete_content(content_id=post_a_id, current_user=user_b)
        assert exc_del.value.status_code == 403
        assert "permission" in exc_del.value.detail.lower()

        # Verify User A's post remains completely unmodified in database
        doc = await db["contents"].find_one({"_id": ObjectId(post_a_id)})
        assert doc is not None
        assert doc["caption"] == "Secret post of User A"


@pytest.mark.asyncio
async def test_case_7_skipping_or_partial_brand_kit_does_not_erase_saved_data():
    """
    Case 7: Skipping or partially completing Brand Kit does not erase previously saved data:
    - Any omitted, null, or empty string values in draft/skip payloads do NOT overwrite existing saved fields.
    - Explicit skip endpoint dismisses popup while leaving all brand data intact.
    """
    db = MockDatabase()
    user_id = str(ObjectId())
    user_doc = {
        "_id": ObjectId(user_id),
        "id": user_id,
        "name": "Preservation Tester",
        "email": "preserve@test.com",
        "role": "businessman",
        "online_presence": "no_online_presence"
    }
    await db["users"].insert_one(user_doc)
    await db["businesses"].insert_one({
        "_id": ObjectId(),
        "owner_id": user_id,
        "name": "Preserved Brand Store",
        "online_presence": "no_online_presence"
    })

    # Initially user saved business name, tagline, primary color, and font
    initial_kit = {
        "business_name": "Preserved Brand Store",
        "tagline": "Quality Guaranteed",
        "primary_color": "#1E40AF",
        "font": "Poppins",
        "brand_kit_status": "in_progress"
    }
    saved_initial = await save_brand_kit_submission(
        db,
        owner_id=user_id,
        submission_data=initial_kit,
        is_draft=True
    )
    assert saved_initial["primary_color"] == "#1E40AF"
    assert saved_initial["font"] == "Poppins"
    assert saved_initial["tagline"] == "Quality Guaranteed"

    # Now user partially updates or skips with empty strings and nulls
    partial_skip_payload = {
        "primary_color": "",            # empty string must NOT erase #1E40AF
        "tagline": None,                # null must NOT erase 'Quality Guaranteed'
        "font": "",                     # empty string must NOT erase 'Poppins'
        "secondary_color": "#F59E0B"    # new valid field added
    }

    updated_kit = await save_brand_kit_submission(
        db,
        owner_id=user_id,
        submission_data=partial_skip_payload,
        is_draft=True
    )

    # Verify preserved fields
    assert updated_kit["primary_color"] == "#1E40AF"
    assert updated_kit["font"] == "Poppins"
    assert updated_kit["tagline"] == "Quality Guaranteed"
    assert updated_kit["secondary_color"] == "#F59E0B"

    # Verify persisted in database collection
    in_db = await db["brand_kits"].find_one({"owner_id": user_id})
    assert in_db["primary_color"] == "#1E40AF"
    assert in_db["font"] == "Poppins"
    assert in_db["tagline"] == "Quality Guaranteed"
    assert in_db["secondary_color"] == "#F59E0B"

    # Test dismissing/skipping via dismiss endpoint
    from app.api.endpoints.brand import dismiss_brand_kit_modal
    dismiss_res = await dismiss_brand_kit_modal(current_user=user_doc, db=db)
    assert dismiss_res["success"] is True
    assert dismiss_res["should_show_modal"] is False

    # Verify brand data still perfectly intact after dismiss/skip
    after_dismiss = await db["brand_kits"].find_one({"owner_id": user_id})
    assert after_dismiss["primary_color"] == "#1E40AF"
    assert after_dismiss["secondary_color"] == "#F59E0B"
    assert after_dismiss["brand_kit_dismissed"] is True
