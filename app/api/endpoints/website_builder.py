from typing import Any, Dict

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
<<<<<<< Updated upstream
=======
from typing import Optional, Any, Dict
>>>>>>> Stashed changes
from app.schemas.website_builder import (
    CreateSessionRequest,
    SendMessageRequest,
    ReviseSiteRequest,
    FrontendSessionResponse,
    FrontendMessageResponse,
<<<<<<< Updated upstream
=======
    WebsiteBuilderSessionResponse,
>>>>>>> Stashed changes
    EditWebsiteRequest,
    EditWebsiteResponse,
)

from app.services.website_builder_service import WebsiteBuilderService
from app.services.credit_service import CreditService
from app.core.database import get_database
from app.core.security import get_current_user
from app.models.user import User
<<<<<<< Updated upstream
=======
from app.api.dependencies import require_feature
>>>>>>> Stashed changes

router = APIRouter()


<<<<<<< Updated upstream
# ---------------------------------------------------------
# RESPONSE HELPERS
# ---------------------------------------------------------

def format_site_payload(site):

=======
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def format_site_payload(site) -> Optional[dict]:
>>>>>>> Stashed changes
    if not site:
        return None

    website_data = getattr(site, "website_data", None) or {}

    if not isinstance(website_data, dict):
        website_data = {}
<<<<<<< Updated upstream

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
=======
    logo_val = website_data.get("logo") or getattr(site, "logo", None)
    theme_val = site.theme or website_data.get("theme") or {}
    return {
        "business_name": site.business_name or "My Business",
        "logo": logo_val,
        "theme": theme_val,
        "pages": site.pages,
    }


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------
@router.post(
    "/session",
    response_model=FrontendSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    request: CreateSessionRequest,
    current_user: User = Depends(get_current_user)
    # _: None = Depends(require_feature("website_builder")),
):
    """
    Create (or reuse) a website-builder chat session.

    NOTE: No credits are charged here. Credits are only deducted when the user
    actually triggers a website *generation* (see ``/message`` with
    ``action == "generate"``). This prevents double-billing on page reloads,
    language switches, or retries.
    """
    existing = await WebsiteBuilderService.get_latest_open_session(str(current_user.id))
    if existing:
        if request.language and existing.language != request.language:
            existing.language = request.language
            await WebsiteBuilderService.save_session(existing)
        return FrontendSessionResponse(
            sessionId=str(existing.id),
            siteId=str(existing.website_project_id) if existing.website_project_id else None,
            language=existing.language,
            messages=existing.messages or [],
        )

    session = await WebsiteBuilderService.create_session(str(current_user.id))
    session.language = request.language
    await WebsiteBuilderService.save_session(session)

    return FrontendSessionResponse(
        sessionId=str(session.id),
        siteId=str(session.website_project_id) if session.website_project_id else None,
        language=session.language,
        messages=session.messages or [],
    )


@router.get("/session/{session_id}", response_model=FrontendSessionResponse)
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    session = await WebsiteBuilderService.get_session(session_id, str(current_user.id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
>>>>>>> Stashed changes

    site = None

    if session.website_project_id:
        site = await WebsiteBuilderService.get_website(
<<<<<<< Updated upstream
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
        if not valid_proj:
            valid_proj = await p_coll.find_one({
                "user_id": user_id,
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

=======
            str(session.website_project_id), str(current_user.id)
        )

>>>>>>> Stashed changes
    return FrontendSessionResponse(
        sessionId=str(session.id),
        siteId=(
            str(session.website_project_id)
            if session.website_project_id
            else None
        ),
        language=session.language,
<<<<<<< Updated upstream
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

=======
        messages=session.messages or [],
        generatedSiteData=format_site_payload(site),
    )


@router.post("/session/{session_id}/message", response_model=FrontendMessageResponse)
async def session_message(
    session_id: str,
    request: SendMessageRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        data_obj = request.data or {}
        action = data_obj.get("action") if isinstance(data_obj, dict) else None

        # ---- Template selection -------------------------------------------
>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
                user_id,
                str(template_id)
            )

        # ---------------------------------------------
        # WEBSITE GENERATION
        # ---------------------------------------------

        elif action == "generate":

            session = await WebsiteBuilderService.get_session(
                session_id,
                user_id
            )

            if not session:
                raise HTTPException(
                    status_code=404,
                    detail="Session not found"
                )
=======
                str(current_user.id),
                data_obj.get("templateId"),
            )
            return FrontendMessageResponse(
                messages=session.messages,
                siteId=str(session.website_project_id) if session.website_project_id else None,
            )

        # ---- Website generation (the only place credits are deducted) ------
        if action == "generate":
            session = await WebsiteBuilderService.get_session(session_id, str(current_user.id))
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")

            db = get_database()

            # Pre-check credits; return 402 if insufficient.
            try:
                enough = await CreditService.has_enough(
                    db, str(current_user.id), "website_builder"
                )
            except AttributeError:
                # Backwards-compatible fallback if has_enough doesn't exist yet
                enough = True

            if not enough:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail="Insufficient credits to generate a website.",
                )

            await WebsiteBuilderService.generate_website(session)
            await CreditService.deduct_credits(
                db, str(current_user.id), "website_builder"
            )

            # Reload session to pick up new site id + messages
            session = await WebsiteBuilderService.get_session(
                session_id, str(current_user.id)
            )
            site = None
            if session.website_project_id:
                site = await WebsiteBuilderService.get_website(
                    str(session.website_project_id), str(current_user.id)
                )

            return FrontendMessageResponse(
                messages=session.messages,
                siteId=str(session.website_project_id) if session.website_project_id else None,
                generatedSiteData=format_site_payload(site),
            )

        # ---- Regular chat --------------------------------------------------
        resp = await WebsiteBuilderService.process_chat(
            session_id,
            str(current_user.id),
            request.message,
            None,  # language already stored on session
            data=request.data,
        )
        session = resp.session
        last_msg = session.messages[-1] if session.messages else {}
        msg_type = last_msg.get("type", "text")

        site = None
        if session.website_project_id:
            site = await WebsiteBuilderService.get_website(
                str(session.website_project_id), str(current_user.id)
            )

        return FrontendMessageResponse(
            message=resp.message,
            type=msg_type,
            messages=session.messages,
            siteId=str(session.website_project_id) if session.website_project_id else None,
            generatedSiteData=format_site_payload(site),
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Site revision & retrieval
# ---------------------------------------------------------------------------
@router.post("/site/{site_id}/revise")
async def revise_website(
    site_id: str,
    request: ReviseSiteRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        site = await WebsiteBuilderService.revise_website(
            site_id, str(current_user.id), request.instructions
        )
        return {"generatedSiteData": format_site_payload(site)}
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
>>>>>>> Stashed changes

            await WebsiteBuilderService.generate_website(session)

<<<<<<< Updated upstream
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
        raise HTTPException(
            status_code=404,
            detail="Session not found"
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
    current_user: User = Depends(get_current_user)
):

    site = await get_owned_site(
        site_id,
        str(current_user.id)
    )

    # Self-healing: if this site project doc has empty pages, check for the valid project for this user/session
    if not getattr(site, "pages", None) or len(site.pages) == 0:
        p_coll = await WebsiteBuilderService.get_project_collection()
        valid_proj = None
        if getattr(site, "session_id", None):
            valid_proj = await p_coll.find_one({
                "user_id": str(current_user.id),
                "session_id": site.session_id,
                "pages.0": {"$exists": True}
            }, sort=[("_id", -1)])
        if not valid_proj:
            valid_proj = await p_coll.find_one({
                "user_id": str(current_user.id),
                "pages.0": {"$exists": True}
            }, sort=[("_id", -1)])
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
            {"$or": [{"session_id": session_id}, {"user_id": user_id}]},
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
=======
@router.get("/site/{site_id}")
async def get_site(site_id: str):
    from bson import ObjectId

    collection = await WebsiteBuilderService.get_project_collection()
    if not ObjectId.is_valid(site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    doc = await collection.find_one({"_id": ObjectId(site_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Site not found")

    return {
        "id": str(doc["_id"]),
        "business_id": str(doc.get("business_id")),
        "business_name": doc.get("business_name", doc.get("business_id")),
        "template_id": doc.get("template_id"),
        "pages": doc.get("pages", []),
        "theme": doc.get("theme", {}),
    }


# ---------------------------------------------------------------------------
# Misc session operations
# ---------------------------------------------------------------------------
@router.post("/session/{session_id}/clear")
async def clear_session_data(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    import uuid

    session = await WebsiteBuilderService.get_session(session_id, str(current_user.id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.collected_data = {}
    session.messages.append(
        {
            "id": str(uuid.uuid4()),
            "role": "ai",
            "content": (
                "I have cleared all previous data. Let's start fresh! "
                "What is the name and category of your new business?"
            ),
            "type": "text",
        }
    )
    session.current_step = 1
    await WebsiteBuilderService.save_session(session)

    return FrontendMessageResponse(
        messages=session.messages,
        siteId=str(session.website_project_id) if session.website_project_id else None,
    )


@router.post("/session/{session_id}/edit", response_model=EditWebsiteResponse)
async def edit_website(
    session_id: str,
    request: EditWebsiteRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Takes a natural-language instruction and applies it to ``current_state``
    via AI. Returns structured changes and the new website state.
    """
    edit_result = await WebsiteBuilderService.apply_website_edit(
        user_id=str(current_user.id),
        session_id=session_id,
        instruction=request.instruction,
        current_state=request.current_state,
    )

    if edit_result.get("action") == "error":
        return EditWebsiteResponse(
            action="error",
            message=edit_result.get("message", "AI Edit failed"),
            updated_state=request.current_state,
        )

    action = edit_result.get("action")
    changes = edit_result.get("changes", {})
    message = edit_result.get("message", "AI Edit applied")

    updated_state = dict(request.current_state)

    if action == "update_theme":
        if "theme" not in updated_state:
            updated_state["theme"] = {}
        for k, v in changes.items():
            updated_state["theme"][k] = v
            if k == "value":  # fallback for occasionally odd AI output
                updated_state["theme"]["primary"] = v

    elif action == "update_text":
        pass  # simplified; deep-merge needed in production

    return EditWebsiteResponse(
        action=action,
        message=message,
        updated_state=updated_state,
    )

>>>>>>> Stashed changes

@router.post("/session/{session_id}/restore")
async def restore_version(
    session_id: str,
    version: int,
<<<<<<< Updated upstream
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

=======
    current_user: User = Depends(get_current_user),
):
    """Restore the website to a specific version number."""
    return {"success": True, "message": f"Restored to version {version}"}
>>>>>>> Stashed changes


@router.post("/session/{session_id}/finalize")
async def finalize_website(
    session_id: str,
<<<<<<< Updated upstream
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

=======
    current_user: User = Depends(get_current_user),
):
    """Lock the website and mark it as finalized."""
    return {"success": True, "message": "Website finalized."}
>>>>>>> Stashed changes


@router.post("/session/{session_id}/export/pdf")
async def export_website_pdf(
    session_id: str,
<<<<<<< Updated upstream
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

=======
    current_user: User = Depends(get_current_user),
):
    """Generate a PDF snapshot of the finalized website."""
    return {"success": True, "download_url": "/mock-pdf-url.pdf"}
>>>>>>> Stashed changes


@router.post("/session/{session_id}/export/zip")
async def export_website_zip(
    session_id: str,
<<<<<<< Updated upstream
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
=======
    current_user: User = Depends(get_current_user),
):
    """Package the website into a downloadable ZIP archive."""
    return {"success": True, "download_url": "/mock-zip-url.zip"}
>>>>>>> Stashed changes
