from app.models.website_builder import WebsiteProject
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.website_builder import (
    CreateSessionRequest,
    SendMessageRequest,
    ReviseSiteRequest,
    FrontendSessionResponse,
    FrontendMessageResponse,
    EditWebsiteRequest,
    EditWebsiteResponse,
)

from app.services.website_builder_service import WebsiteBuilderService
from app.services.credit_service import CreditService
from app.core.database import get_database
from app.core.security import get_current_user, get_current_user_optional, CurrentUser
from app.models.user import User

router = APIRouter()


# ---------------------------------------------------------
# RESPONSE HELPERS
# ---------------------------------------------------------

def format_site_payload(site):

    if not site:
        return None

    website_data = getattr(site, "website_data", None) or {}

    if not isinstance(website_data, dict):
        website_data = {}

    logo = (
        website_data.get("logo")
        or getattr(site, "logo", None)
    )

    theme = (
        getattr(site, "theme", None)
        or website_data.get("theme")
        or {}
    )

    pages = (
        getattr(site, "pages", None)
        or website_data.get("pages")
        or []
    )

    return {
        "business_name": getattr(site, "business_name", None),
        "logo": logo,
        "theme": theme,
        "pages": pages,
    }


async def get_owned_site(site_id: str, user_id: str):

    if not ObjectId.is_valid(site_id):
        raise HTTPException(
            status_code=404,
            detail="Website not found"
        )

    site = await WebsiteBuilderService.get_website(
        site_id,
        user_id
    )

    if not site:
        raise HTTPException(
            status_code=404,
            detail="Website not found"
        )

    return site


async def get_session_and_site(session_id: str, user_id: str):

    session = await WebsiteBuilderService.get_session(
        session_id,
        user_id
    )

    if not session:
        raise HTTPException(
            status_code=404,
            detail="Session not found"
        )

    site = None

    if session.website_project_id:
        site = await WebsiteBuilderService.get_website(
            str(session.website_project_id),
            user_id
        )

    # Self-healing: if session.website_project_id is missing OR points to a project with empty pages,
    # find the most recent project for this session/user that has valid pages!
    if not site or not getattr(site, "pages", None) or len(site.pages) == 0:
        p_coll = await WebsiteBuilderService.get_project_collection()
        valid_proj = await p_coll.find_one({
            "user_id": user_id,
            "session_id": session_id,
            "pages.0": {"$exists": True}
        }, sort=[("_id", -1)])


        if valid_proj:
            site = WebsiteProject(**valid_proj)
            session.website_project_id = str(valid_proj["_id"])
            if session.current_step < 8:
                session.current_step = 8
            session.collected_data["onboarding_step"] = "generated"
            await WebsiteBuilderService.save_session(session)

    return session, site


# ---------------------------------------------------------
# CREATE SESSION
# ---------------------------------------------------------

@router.post(
    "/session",
    response_model=FrontendSessionResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_session(
    request: CreateSessionRequest,
    current_user: User = Depends(get_current_user)
):

    session = await WebsiteBuilderService.create_session(
        str(current_user.id)
    )

    session.language = request.language or "English"

    await WebsiteBuilderService.save_session(session)

    return FrontendSessionResponse(
        sessionId=str(session.id),
        siteId=(
            str(session.website_project_id)
            if session.website_project_id
            else None
        ),
        language=session.language,
        messages=session.messages,
    )


# ---------------------------------------------------------
# GET SESSION
# ---------------------------------------------------------

@router.get(
    "/session/{session_id}",
    response_model=FrontendSessionResponse
)
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user)
):

    session, site = await get_session_and_site(
        session_id,
        str(current_user.id)
    )

    return FrontendSessionResponse(
        sessionId=str(session.id),
        siteId=(
            str(session.website_project_id)
            if session.website_project_id
            else None
        ),
        language=session.language,
        messages=session.messages,
        generatedSiteData=format_site_payload(site),
    )


# ---------------------------------------------------------
# SEND CHAT MESSAGE
# ---------------------------------------------------------

@router.post(
    "/session/{session_id}/message",
    response_model=FrontendMessageResponse
)
async def session_message(
    session_id: str,
    request: SendMessageRequest,
    current_user: User = Depends(get_current_user)
):

    user_id = str(current_user.id)

    try:

        data = request.data or {}

        if not isinstance(data, dict):
            data = {}

        action = data.get("action")

        # ---------------------------------------------
        # TEMPLATE SELECTION
        # ---------------------------------------------

        if action == "select_template":

            template_id = (
                data.get("templateId")
                or data.get("template_id")
            )

            if not template_id:
                raise HTTPException(
                    status_code=400,
                    detail="Template ID is required"
                )

            session = await WebsiteBuilderService.select_template(
                session_id,
                user_id,
                str(template_id)
            )

        # ---------------------------------------------
        # WEBSITE GENERATION
        # ---------------------------------------------

        elif action in ["generate", "build_directly"]:

            session = await WebsiteBuilderService.get_session(
                session_id,
                user_id
            )

            if not session:
                raise HTTPException(
                    status_code=404,
                    detail="Session not found"
                )

            # HIGHEST PRIORITY: The data explicitly answered by the user in this session!
            # Never overwrite what user answered in chat with the user profile account name!
            biz_name = session.collected_data.get("Business Name")
            if not biz_name and data.get("business_name") and data.get("business_name") not in ["BIBA Fashion Limited", "Business", "My Business"]:
                biz_name = data.get("business_name")
            if not biz_name and current_user:
                biz_name = getattr(current_user, "business_name", None) or getattr(current_user, "brand_name", None) or getattr(current_user, "company_name", None)
            if not biz_name:
                db = get_database()
                u_doc = await db.users.find_one({"_id": ObjectId(user_id)}) if ObjectId.is_valid(user_id) else None
                if u_doc:
                    biz_name = u_doc.get("business_name") or u_doc.get("brand_name") or u_doc.get("company_name")
            if not biz_name:
                biz_name = "Business"

            biz_cat = session.collected_data.get("Business Category")
            if not biz_cat and data.get("business_category") and data.get("business_category") != "Business":
                biz_cat = data.get("business_category")
            if not biz_cat:
                biz_cat = "Business"

            session.collected_data["Business Name"] = biz_name
            session.collected_data["Business Category"] = biz_cat
            if data.get("industry_details"):
                session.collected_data["industry_details"] = data.get("industry_details")
            if data.get("products_services"):
                session.collected_data["Products/Services"] = data.get("products_services")
            if data.get("location"):
                session.collected_data["Location & Contact"] = data.get("location")

            if not session.collected_data.get("Logo"):
                theme = WebsiteBuilderService.resolve_palette(category=biz_cat)
                session.collected_data["Logo"] = WebsiteBuilderService.generate_dynamic_logo(
                    biz_name, biz_cat, theme["primary"]
                )
                session.collected_data["logo_status"] = "available"

            WebsiteBuilderService.add_user_message(session, request.message or "Build directly")
            await WebsiteBuilderService.generate_website(session, user_id)

            session = await WebsiteBuilderService.get_session(
                session_id,
                user_id
            )

            if not session:
                raise HTTPException(
                    status_code=404,
                    detail="Session not found after generation"
                )

        # ---------------------------------------------
        # NORMAL CHAT
        # ---------------------------------------------

        else:

            response = await WebsiteBuilderService.process_chat(
                session_id=session_id,
                user_id=user_id,
                message=request.message,
                language=None,
                data=data,
            )

            session = response.session

            if not session:
                raise HTTPException(
                    status_code=500,
                    detail="Website Builder returned an invalid session"
                )

        # ---------------------------------------------
        # FETCH GENERATED WEBSITE
        # ---------------------------------------------

        site = None

        if session.website_project_id:

            site = await WebsiteBuilderService.get_website(
                str(session.website_project_id),
                user_id
            )

        last_message = (
            session.messages[-1]
            if session.messages
            else {}
        )

        return FrontendMessageResponse(
            message=last_message.get("content"),
            type=last_message.get("type", "text"),
            data=last_message.get("data"),
            messages=session.messages,
            siteId=(
                str(session.website_project_id)
                if session.website_project_id
                else None
            ),
            generatedSiteData=format_site_payload(site),
        )

    except HTTPException:
        raise

    except Exception:
        import logging

        logging.exception(
            "Website Builder message processing failed"
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to process your Website Builder message."
        )


# ---------------------------------------------------------
# REVISE WEBSITE
# ---------------------------------------------------------

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Site revision & retrieval
# ---------------------------------------------------------------------------
@router.post("/site/{site_id}/revise")
async def revise_website(
    site_id: str,
    request: ReviseSiteRequest,
    current_user: User = Depends(get_current_user)
):

    user_id = str(current_user.id)

    try:

        site = await WebsiteBuilderService.revise_website(
            site_id,
            user_id,
            request.instructions
        )

        return {
            "generatedSiteData": format_site_payload(site)
        }

    except HTTPException:
        raise

    except Exception:

        import logging

        logging.exception("Website revision failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to revise the website."
        )


# ---------------------------------------------------------
# CLEAR SESSION
# ---------------------------------------------------------

@router.post("/session/{session_id}/clear")
async def clear_session_data(
    session_id: str,
    current_user: User = Depends(get_current_user)
):

    session = await WebsiteBuilderService.get_session(
        session_id,
        str(current_user.id)
    )

    if not session:
        new_sess = await WebsiteBuilderService.create_session(str(current_user.id))
        return FrontendMessageResponse(
            message=new_sess.messages[-1]["content"] if new_sess.messages else "I have cleared all previous data. Let's start fresh!",
            messages=new_sess.messages,
            siteId=None,
        )

    import uuid

    session.collected_data = {}
    session.current_step = 1
    session.selected_template = None
    session.recommendations = []
    session.website_project_id = None

    session.messages = [
        {
            "id": str(uuid.uuid4()),
            "role": "ai",
            "content": (
                "I have cleared all previous data. "
                "Let's start fresh! What type of business do you run, "
                "and what products or services do you offer?"
            ),
            "type": "text"
        }
    ]

    await WebsiteBuilderService.save_session(session)

    return FrontendMessageResponse(
        message=session.messages[-1]["content"],
        messages=session.messages,
        siteId=None,
    )


# ---------------------------------------------------------
# GET WEBSITE
# ---------------------------------------------------------

@router.get("/site/{site_id}")
async def get_site(
    site_id: str,
    current_user: Optional[CurrentUser] = Depends(get_current_user_optional)
):
    if not ObjectId.is_valid(site_id):
        raise HTTPException(
            status_code=404,
            detail="Website not found"
        )

    user_id = None
    if current_user:
        user_id = str(current_user.get("id") or current_user.get("_id") or "")

    p_coll = await WebsiteBuilderService.get_project_collection()
    site_doc = await p_coll.find_one({"_id": ObjectId(site_id)})
    if not site_doc:
        raise HTTPException(
            status_code=404,
            detail="Website not found"
        )

    site = WebsiteProject(**site_doc)

    # Self-healing: if this site project doc has empty pages, check for a valid project in this session or for this user
    payload = format_site_payload(site)
    if not payload["pages"] or len(payload["pages"]) == 0:
        session_id = getattr(site, "session_id", None)
        valid_proj = None
        if session_id:
            cursor = p_coll.find({"session_id": session_id}).sort([("_id", -1)])
            candidates = await cursor.to_list(length=10)
            for c_doc in candidates:
                cand_pages = c_doc.get("pages") or (c_doc.get("website_data", {}).get("pages") if isinstance(c_doc.get("website_data"), dict) else [])
                if cand_pages and len(cand_pages) > 0:
                    valid_proj = c_doc
                    break

        if valid_proj:
            site = WebsiteProject(**valid_proj)
            payload = format_site_payload(site)

    return {
        "id": str(site.id),
        "business_id": site.business_id,
        "business_name": site.business_name,
        "template_id": site.template_id,
        "pages": payload["pages"],
        "theme": payload["theme"],
        "logo": payload["logo"],
    }


# ---------------------------------------------------------
# DIRECT WEBSITE EDIT
# ---------------------------------------------------------

@router.post(
    "/session/{session_id}/edit",
    response_model=EditWebsiteResponse
)
async def edit_website(
    session_id: str,
    request: EditWebsiteRequest,
    current_user: User = Depends(get_current_user)
):

    user_id = str(current_user.id)

    session = await WebsiteBuilderService.get_session(
        session_id,
        user_id
    )

    if not session:
        raise HTTPException(
            status_code=404,
            detail="Session not found"
        )

    if not session.website_project_id:
        p_coll = await WebsiteBuilderService.get_project_collection()
        recent_proj = await p_coll.find_one(
            {"session_id": session_id, "user_id": user_id},
            sort=[("created_at", -1)]
        )
        if recent_proj:
            session.website_project_id = str(recent_proj["_id"])
            await WebsiteBuilderService.save_session(session)
        elif request.current_state and (request.current_state.get("pages") or request.current_state.get("sections")):
            from datetime import datetime, timezone
            proj_doc = {
                "user_id": user_id,
                "session_id": session_id,
                "business_name": request.current_state.get("business_name", "My Business"),
                "business_category": request.current_state.get("business_category", "Business"),
                "website_data": request.current_state,
                "theme": request.current_state.get("theme", {}),
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            }
            res = await p_coll.insert_one(proj_doc)
            session.website_project_id = str(res.inserted_id)
            await WebsiteBuilderService.save_session(session)
        else:
            raise HTTPException(
                status_code=400,
                detail="Generate a website before editing it."
            )

    edit_result = await WebsiteBuilderService.apply_website_edit(
        user_id=user_id,
        session_id=session_id,
        instruction=request.user_instruction,
        current_state=request.current_state,
    )

    if not isinstance(edit_result, dict):
        raise HTTPException(
            status_code=502,
            detail="Invalid AI edit response"
        )

    action = edit_result.get("action", "error")

    if action == "error":
        return EditWebsiteResponse(
            action="error",
            message=edit_result.get(
                "message",
                "Unable to apply website changes."
            ),
            updated_state=request.current_state,
        )

    if action == "clarification_required":
        return EditWebsiteResponse(
            action=action,
            message=edit_result.get(
                "message",
                "Please clarify this change."
            ),
            updated_state=request.current_state,
        )

    if action == "ask_color":
        return EditWebsiteResponse(
            action=action,
            message=edit_result.get("message", "Which color would you like for your website?"),
            options=edit_result.get("options", []),
            updated_state=request.current_state,
        )

    updated_state = edit_result.get("updated_state")

    if not isinstance(updated_state, dict):
        # The existing service may return action + changes rather
        # than a complete updated_state. Do not claim that it edited
        # the website if no updated state was actually produced.
        return EditWebsiteResponse(
            action="error",
            message=(
                "The AI returned edit instructions but did not "
                "return an updated website. No changes were saved."
            ),
            updated_state=request.current_state,
        )

    # ---------------------------------------------
    # PERSIST UPDATED WEBSITE
    # ---------------------------------------------

    collection = await WebsiteBuilderService.get_project_collection()

    update_fields = {
        "website_data": updated_state,
        "updated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ),
    }

    if "pages" in updated_state:
        update_fields["pages"] = updated_state["pages"]

    if "theme" in updated_state:
        update_fields["theme"] = updated_state["theme"]

    result = await collection.update_one(
        {
            "_id": ObjectId(session.website_project_id),
            "user_id": user_id,
        },
        {
            "$set": update_fields,
            "$inc": {"version": 1},
        },
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Website project not found"
        )

    return EditWebsiteResponse(
        action=action,
        target=edit_result.get("target"),
        changes=edit_result.get("changes"),
        message=edit_result.get(
            "message",
            "Website updated successfully."
        ),
        updated_state=updated_state,
    )


# ---------------------------------------------------------
# RESTORE VERSION
# ---------------------------------------------------------

@router.post("/session/{session_id}/restore")
async def restore_version(
    session_id: str,
    version: int,
    current_user: User = Depends(get_current_user)
):

    session = await WebsiteBuilderService.get_session(
        session_id,
        str(current_user.id)
    )

    if not session:
        raise HTTPException(
            status_code=404,
            detail="Session not found"
        )

    raise HTTPException(
        status_code=501,
        detail="Website version restoration is not implemented yet."
    )


# ---------------------------------------------------------
# FINALIZE WEBSITE
# ---------------------------------------------------------


@router.post("/session/{session_id}/finalize")
async def finalize_website(
    session_id: str,
    current_user: User = Depends(get_current_user)
):

    session = await WebsiteBuilderService.get_session(
        session_id,
        str(current_user.id)
    )

    if not session:
        raise HTTPException(
            status_code=404,
            detail="Session not found"
        )

    raise HTTPException(
        status_code=501,
        detail="Website finalization is not implemented yet."
    )


# ---------------------------------------------------------
# EXPORT PDF
# ---------------------------------------------------------


@router.post("/session/{session_id}/export/pdf")
async def export_website_pdf(
    session_id: str,
    current_user: User = Depends(get_current_user)
):

    session = await WebsiteBuilderService.get_session(
        session_id,
        str(current_user.id)
    )

    if not session:
        raise HTTPException(
            status_code=404,
            detail="Session not found"
        )

    if not session.website_project_id:
        raise HTTPException(
            status_code=400,
            detail="No generated website found."
        )

    download_url = await WebsiteBuilderService.generate_pdf_snapshot(
        str(session.website_project_id)
    )

    return {
        "success": True,
        "download_url": download_url,
    }


# ---------------------------------------------------------
# EXPORT ZIP
# ---------------------------------------------------------


@router.post("/session/{session_id}/export/zip")
async def export_website_zip(
    session_id: str,
    current_user: User = Depends(get_current_user)
):

    session = await WebsiteBuilderService.get_session(
        session_id,
        str(current_user.id)
    )

    if not session:
        raise HTTPException(
            status_code=404,
            detail="Session not found"
        )

    if not session.website_project_id:
        raise HTTPException(
            status_code=400,
            detail="No generated website found."
        )

    site = await WebsiteBuilderService.get_website(
        str(session.website_project_id),
        str(current_user.id)
    )

    if not site:
        raise HTTPException(
            status_code=404,
            detail="Website not found"
        )

    download_url = await WebsiteBuilderService.generate_zip_archive(
        {
            "pages": site.pages,
            "theme": site.theme,
            "business_name": site.business_name,
        },
        str(site.id)
    )

    return {
        "success": True,
        "download_url": download_url,
    }
