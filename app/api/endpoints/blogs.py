from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import List, Optional, Any
from bson import ObjectId
from datetime import datetime
import re

from app.core.security import require_admin, CurrentUser
from app.core.database import get_database
from app.schemas.blog import BlogCreate, BlogUpdate, BlogPostResponse

router = APIRouter()

def clean_doc(doc: dict) -> dict:
    if not doc:
        return doc
    doc["id"] = str(doc["_id"])
    del doc["_id"]
    return doc

def make_slug(title: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9\s-]', '', title).lower()
    return re.sub(r'[\s-]+', '-', cleaned).strip('-')

# ----------------- PUBLIC ENDPOINTS -----------------

@router.get("", response_model=List[BlogPostResponse])
async def list_published_blogs(
    category: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    skip: int = Query(0, ge=0)
):
    db = get_database()
    query: dict = {"published": True}
    if category and category.lower() != "all":
        query["category"] = {"$regex": f"^{re.escape(category)}$", "$options": "i"}
    if search:
        query["$or"] = [
            {"title": {"$regex": re.escape(search), "$options": "i"}},
            {"excerpt": {"$regex": re.escape(search), "$options": "i"}},
            {"tags": {"$in": [re.compile(re.escape(search), re.IGNORECASE)]}}
        ]
    cursor = db["blogs"].find(query).sort("created_at", -1).skip(skip).limit(limit)
    blogs = await cursor.to_list(length=limit)
    return [clean_doc(b) for b in blogs]

@router.get("/{slug_or_id}", response_model=BlogPostResponse)
async def get_blog_by_slug_or_id(slug_or_id: str):
    db = get_database()
    query: dict = {"slug": slug_or_id}
    if ObjectId.isValid(slug_or_id) if hasattr(ObjectId, 'isValid') else len(slug_or_id) == 24:
        try:
            query = {"$or": [{"_id": ObjectId(slug_or_id)}, {"slug": slug_or_id}]}
        except Exception:
            pass

    blog = await db["blogs"].find_one_and_update(
        query,
        {"$inc": {"views": 1}},
        return_document=True
    )
    if not blog:
        raise HTTPException(status_code=404, detail="Blog post not found")
    return clean_doc(blog)

# ----------------- ADMIN ENDPOINTS -----------------

@router.get("/admin/all", response_model=Any)
async def admin_list_blogs(
    status_filter: Optional[str] = Query(None, alias="status"),
    category: Optional[str] = None,
    search: Optional[str] = None,
    current_user: CurrentUser = Depends(require_admin)
):
    db = get_database()
    query: dict = {}

    if status_filter and status_filter.lower() != "all":
        if status_filter.lower() == "published":
            query["published"] = True
        elif status_filter.lower() == "draft":
            query["published"] = False

    if category and category.lower() != "all":
        query["category"] = {"$regex": f"^{re.escape(category)}$", "$options": "i"}

    if search:
        query["$or"] = [
            {"title": {"$regex": re.escape(search), "$options": "i"}},
            {"excerpt": {"$regex": re.escape(search), "$options": "i"}},
            {"author": {"$regex": re.escape(search), "$options": "i"}}
        ]

    cursor = db["blogs"].find(query).sort("created_at", -1)
    blogs = await cursor.to_list(length=200)

    # Compute overall stats
    total_count = await db["blogs"].count_documents({})
    published_count = await db["blogs"].count_documents({"published": True})
    draft_count = await db["blogs"].count_documents({"published": False})

    # Total views across all posts
    pipeline = [{"$group": {"_id": None, "total_views": {"$sum": "$views"}}}]
    views_res = await db["blogs"].aggregate(pipeline).to_list(length=1)
    total_views = views_res[0]["total_views"] if views_res else 0

    return {
        "posts": [clean_doc(b) for b in blogs],
        "stats": {
            "total": total_count,
            "published": published_count,
            "drafts": draft_count,
            "total_views": total_views
        }
    }

@router.get("/admin/{id}", response_model=BlogPostResponse)
async def admin_get_blog(id: str, current_user: CurrentUser = Depends(require_admin)):
    db = get_database()
    try:
        query = {"$or": [{"_id": ObjectId(id)}, {"id": id}]}
    except Exception:
        query = {"id": id}

    blog = await db["blogs"].find_one(query)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog post not found")
    return clean_doc(blog)

@router.post("/admin", response_model=BlogPostResponse, status_code=status.HTTP_201_CREATED)
async def admin_create_blog(
    data: BlogCreate,
    current_user: CurrentUser = Depends(require_admin)
):
    db = get_database()
    now = datetime.utcnow()

    slug = data.slug.strip() if data.slug and data.slug.strip() else make_slug(data.title)

    # Check for duplicate slug
    existing = await db["blogs"].find_one({"slug": slug})
    if existing:
        slug = f"{slug}-{int(now.timestamp())}"

    doc = data.dict()
    doc["slug"] = slug
    doc["views"] = 0
    doc["likes"] = 0
    doc["created_at"] = now
    doc["updated_at"] = now

    res = await db["blogs"].insert_one(doc)
    doc["id"] = str(res.inserted_id)
    if "_id" in doc:
        del doc["_id"]
    return doc

@router.put("/admin/{id}", response_model=BlogPostResponse)
async def admin_update_blog(
    id: str,
    data: BlogUpdate,
    current_user: CurrentUser = Depends(require_admin)
):
    db = get_database()
    now = datetime.utcnow()

    try:
        query = {"$or": [{"_id": ObjectId(id)}, {"id": id}]}
    except Exception:
        query = {"id": id}

    update_fields = {k: v for k, v in data.dict(exclude_unset=True).items() if v is not None}
    if "title" in update_fields and "slug" not in update_fields:
        update_fields["slug"] = make_slug(update_fields["title"])
    update_fields["updated_at"] = now

    updated = await db["blogs"].find_one_and_update(
        query,
        {"$set": update_fields},
        return_document=True
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Blog post not found")
    return clean_doc(updated)

@router.patch("/admin/{id}/toggle-status")
async def admin_toggle_blog_status(
    id: str,
    current_user: CurrentUser = Depends(require_admin)
):
    db = get_database()
    try:
        query = {"$or": [{"_id": ObjectId(id)}, {"id": id}]}
    except Exception:
        query = {"id": id}

    existing = await db["blogs"].find_one(query)
    if not existing:
        raise HTTPException(status_code=404, detail="Blog post not found")

    new_published = not bool(existing.get("published", False))
    await db["blogs"].update_one(query, {"$set": {"published": new_published, "updated_at": datetime.utcnow()}})
    return {"id": str(existing["_id"]), "published": new_published, "message": f"Status updated to {'Published' if new_published else 'Draft'}"}

@router.delete("/admin/{id}")
async def admin_delete_blog(
    id: str,
    current_user: CurrentUser = Depends(require_admin)
):
    db = get_database()
    try:
        query = {"$or": [{"_id": ObjectId(id)}, {"id": id}]}
    except Exception:
        query = {"id": id}

    res = await db["blogs"].delete_one(query)
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Blog post not found")
    return {"success": True, "message": "Blog post deleted successfully", "id": id}
