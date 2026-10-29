import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pymongo.database import Database

from app.api.dependencies import get_database
from app.schemas.lead import (
    LeadCreateRequest,
    LeadUpdateRequest,
    LeadResponse,
    LeadSubmitResponse,
    LeadListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _format_lead_doc(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", ""),
        "email": doc.get("email", ""),
        "subject": doc.get("subject", ""),
        "message": doc.get("message", ""),
        "phone": doc.get("phone"),
        "source": doc.get("source", "website_contact_form"),
        "status": doc.get("status", "new"),
        "notes": doc.get("notes"),
        "assigned_to": doc.get("assigned_to"),
        "ip_address": doc.get("ip_address"),
        "user_agent": doc.get("user_agent"),
        "created_at": doc.get("created_at") or datetime.now(timezone.utc),
        "updated_at": doc.get("updated_at") or datetime.now(timezone.utc),
    }


@router.post("", response_model=LeadSubmitResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=LeadSubmitResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
@router.post("/submit", response_model=LeadSubmitResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
@router.post("/contact", response_model=LeadSubmitResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_lead(
    payload: LeadCreateRequest,
    request: Request,
    db: Database = Depends(get_database),
):
    """
    Submits a contact form inquiry and persists all details into the 'leads' database collection.
    Every detail is stored in distinct, indexed fields for easy reporting and database administration.
    """
    now = datetime.now(timezone.utc)

    # Capture client IP and User Agent for security & verification
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or request.headers.get("x-real-ip")
        or (request.client.host if request.client else None)
    )
    user_agent = request.headers.get("user-agent")

    lead_doc = {
        "name": payload.name.strip(),
        "email": payload.email.lower().strip(),
        "subject": payload.subject.strip(),
        "message": payload.message.strip(),
        "phone": payload.phone.strip() if payload.phone else None,
        "source": payload.source or "website_contact_form",
        "status": "new",
        "notes": None,
        "assigned_to": None,
        "ip_address": client_ip,
        "user_agent": user_agent,
        "created_at": now,
        "updated_at": now,
    }

    result = await db["leads"].insert_one(lead_doc)
    lead_id = str(result.inserted_id)
    lead_doc["_id"] = result.inserted_id

    logger.info(f"New lead captured successfully [ID: {lead_id}] from {payload.name} ({payload.email})")

    return LeadSubmitResponse(
        success=True,
        message="Thank you! Your message has been received. Our team will get back to you soon.",
        lead_id=lead_id,
        data=_format_lead_doc(lead_doc),
    )


@router.get("", response_model=LeadListResponse)
@router.get("/", response_model=LeadListResponse, include_in_schema=False)
async def get_all_leads(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status (new, contacted, in_progress, qualified, closed)"),
    search: Optional[str] = Query(None, description="Search by name, email, or subject"),
    db: Database = Depends(get_database),
):
    """
    Retrieves a paginated list of leads stored in the 'leads' collection.
    Supports filtering by status and text search on name, email, and subject.
    """
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status.strip().lower()

    if search:
        search_regex = {"$regex": search.strip(), "$options": "i"}
        query["$or"] = [
            {"name": search_regex},
            {"email": search_regex},
            {"subject": search_regex},
        ]

    total = await db["leads"].count_documents(query)
    safe_page = max(1, page)
    safe_limit = min(max(1, limit), 100)
    skip = (safe_page - 1) * safe_limit

    cursor = db["leads"].find(query).sort("created_at", -1).skip(skip).limit(safe_limit)

    items = []
    async for doc in cursor:
        items.append(_format_lead_doc(doc))

    total_pages = max(1, (total + safe_limit - 1) // safe_limit)

    return LeadListResponse(
        success=True,
        total=total,
        page=safe_page,
        limit=safe_limit,
        total_pages=total_pages,
        data=items,
    )


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead_by_id(
    lead_id: str,
    db: Database = Depends(get_database),
):
    """
    Retrieves full details of a specific lead by MongoDB ID.
    """
    if not ObjectId.is_valid(lead_id):
        raise HTTPException(status_code=400, detail="Invalid lead ID format")

    doc = await db["leads"].find_one({"_id": ObjectId(lead_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Lead not found")

    return _format_lead_doc(doc)


@router.patch("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: str,
    update_data: LeadUpdateRequest,
    db: Database = Depends(get_database),
):
    """
    Updates lead status, admin notes, or assigned staff in the 'leads' collection.
    """
    if not ObjectId.is_valid(lead_id):
        raise HTTPException(status_code=400, detail="Invalid lead ID format")

    fields_to_update: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if update_data.status is not None:
        fields_to_update["status"] = update_data.status.strip().lower()
    if update_data.notes is not None:
        fields_to_update["notes"] = update_data.notes.strip()
    if update_data.assigned_to is not None:
        fields_to_update["assigned_to"] = update_data.assigned_to.strip()

    result = await db["leads"].find_one_and_update(
        {"_id": ObjectId(lead_id)},
        {"$set": fields_to_update},
        return_document=True,
    )

    if not result:
        raise HTTPException(status_code=404, detail="Lead not found")

    return _format_lead_doc(result)


@router.delete("/{lead_id}")
async def delete_lead(
    lead_id: str,
    db: Database = Depends(get_database),
):
    """
    Deletes a lead entry from the 'leads' collection.
    """
    if not ObjectId.is_valid(lead_id):
        raise HTTPException(status_code=400, detail="Invalid lead ID format")

    res = await db["leads"].delete_one({"_id": ObjectId(lead_id)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")

    return {"success": True, "message": f"Lead {lead_id} deleted successfully"}
