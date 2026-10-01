from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional, Any, Dict
from app.schemas.website_builder import (
    CreateSessionRequest,
    SendMessageRequest,
    ReviseSiteRequest,
    FrontendSessionResponse,
    FrontendMessageResponse,
    WebsiteBuilderSessionResponse
)
from app.services.website_builder_service import WebsiteBuilderService
from app.core.security import get_current_user
from app.models.user import User
from app.api.dependencies import require_feature, require_credits

router = APIRouter()

@router.post("/session", response_model=FrontendSessionResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_feature("website_builder")), Depends(require_credits("website_builder"))])
async def create_session(request: CreateSessionRequest, current_user: User = Depends(get_current_user)):
    from app.core.database import get_database
    from app.services.credit_service import CreditService
    db = get_database()
    await CreditService.deduct_credits(db, str(current_user.id), "website_builder")
    
    session = await WebsiteBuilderService.create_session(str(current_user.id))
    session.language = request.language
    # Optionally re-save session with language, but the service handles it.
    
    return FrontendSessionResponse(
        sessionId=str(session.id),
        siteId=str(session.website_project_id) if session.website_project_id else None,
        language=session.language,
        messages=session.messages
    )

@router.get("/session/{session_id}", response_model=FrontendSessionResponse)
async def get_session(session_id: str, current_user: User = Depends(get_current_user)):
    session = await WebsiteBuilderService.get_session(session_id, str(current_user.id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    site = None
    if session.website_project_id:
        site = await WebsiteBuilderService.get_website(str(session.website_project_id), str(current_user.id))
        
    return FrontendSessionResponse(
        sessionId=str(session.id),
        siteId=str(session.website_project_id) if session.website_project_id else None,
        language=session.language,
        messages=session.messages,
        generatedSiteData=site.pages if site else None
    )

@router.post("/session/{session_id}/message", response_model=FrontendMessageResponse)
async def session_message(session_id: str, request: SendMessageRequest, current_user: User = Depends(get_current_user)):
    try:
        data_obj = request.data or {}
        action = data_obj.get("action") if isinstance(data_obj, dict) else None
        
        if action == "select_template":
            session = await WebsiteBuilderService.select_template(
                session_id,
                str(current_user.id),
                data_obj.get("templateId")
            )
            return FrontendMessageResponse(
                messages=session.messages,
                siteId=str(session.website_project_id) if session.website_project_id else None
            )
            
        elif action == "generate":
            session = await WebsiteBuilderService.get_session(session_id, str(current_user.id))
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            await WebsiteBuilderService.generate_website(session)
            
            # Reload session
            session = await WebsiteBuilderService.get_session(session_id, str(current_user.id))
            site = None
            if session.website_project_id:
                site = await WebsiteBuilderService.get_website(str(session.website_project_id), str(current_user.id))
                
            return FrontendMessageResponse(
                messages=session.messages,
                siteId=str(session.website_project_id) if session.website_project_id else None,
                generatedSiteData=site.pages if site else None
            )
            
        else:
            # Regular chat
            resp = await WebsiteBuilderService.process_chat(
                session_id,
                str(current_user.id),
                request.message,
                None # Language already in session
            )
            session = resp.session
            
            last_msg = session.messages[-1] if session.messages else {}
            msg_type = last_msg.get("type", "text")
            
            site = None
            if session.website_project_id:
                site = await WebsiteBuilderService.get_website(str(session.website_project_id), str(current_user.id))
            
            msg_data = {
                "message": resp.message,
                "type": msg_type,
                "messages": session.messages,
                "siteId": str(session.website_project_id) if session.website_project_id else None,
                "generatedSiteData": site.pages if site else None
            }
                
            return FrontendMessageResponse(**msg_data)
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=traceback.format_exc())

@router.post("/site/{site_id}/revise")
async def revise_website(site_id: str, request: ReviseSiteRequest, current_user: User = Depends(get_current_user)):
    try:
        site = await WebsiteBuilderService.revise_website(site_id, str(current_user.id), request.instructions)
        return {"generatedSiteData": site.pages}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@router.post('/session/{session_id}/clear')
async def clear_session_data(session_id: str, current_user: User = Depends(get_current_user)):
    import uuid
    session = await WebsiteBuilderService.get_session(session_id, str(current_user.id))
    if session:
        session.collected_data = {}
        msg = {
            'id': str(uuid.uuid4()),
            'role': 'ai',
            'content': 'I have cleared all previous data. Let\'s start fresh! What is the name and category of your new business?',
            'type': 'text'
        }
        session.messages.append(msg)
        session.current_step = 1
        await WebsiteBuilderService.save_session(session)
        
        return FrontendMessageResponse(
            messages=session.messages,
            siteId=str(session.website_project_id) if session.website_project_id else None
        )
    raise HTTPException(status_code=404, detail='Session not found')

@router.get("/site/{site_id}")
async def get_site(site_id: str):
    from bson import ObjectId
    collection = await WebsiteBuilderService.get_project_collection()
    if not ObjectId.is_valid(site_id):
        raise HTTPException(status_code=400, detail="Invalid site ID")
    doc = await collection.find_one({"_id": ObjectId(site_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Site not found")
    
    return {
        "id": str(doc["_id"]),
        "business_id": str(doc.get("business_id")),
        "business_name": doc.get("business_name", doc.get("business_id")),
        "template_id": doc.get("template_id"),
        "pages": doc.get("pages", []),
        "theme": doc.get("theme", {})
    }
