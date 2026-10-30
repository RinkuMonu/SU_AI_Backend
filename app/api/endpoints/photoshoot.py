"""
Unified AI Product Photoshoot Studio Endpoints.
Supports both model-based commercial catalog photography and product-only commercial studio photography.
"""

import io
import json
import zipfile
from pathlib import Path
from typing import Optional, List

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse

from app.core.database import get_database
from app.core.security import get_current_user
from app.services.photoshoot_service import PhotoshootService
from app.schemas.photoshoot import (
    ProductUploadResponse,
    ProductAnalysisRequest,
    ProductAnalysisResponse,
    ProductEnhanceRequest,
    ProductEnhanceResponse,
    SelectEnhancedRequest,
    AIModelListResponse,
    PhotographyStylesResponse,
    PreparePromptRequest,
    PreparePromptResponse,
    PhotoshootGenerateRequest,
    PhotoshootGenerateResponse,
    PhotoshootJobStatusResponse,
    PhotoshootResultsResponse,
    SaveImagesRequest,
    SaveImagesResponse,
    RegenerateImageRequest,
    GalleryResponse,
    RetryJobResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _serialize_mongo(obj):
    from bson import ObjectId
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, list):
        return [_serialize_mongo(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialize_mongo(v) for k, v in obj.items()}
    return obj


def _get_user_id(current_user: dict) -> str:
    user_id = str(current_user.get("_id") or current_user.get("id") or "")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user credentials")
    return user_id


# ---------------------------------------------------------------------------
# 1. Product Upload
# ---------------------------------------------------------------------------
@router.post("/upload", response_model=ProductUploadResponse, summary="Upload product images for photoshoot session")
async def upload_product_images(
    files: List[UploadFile] = File(...),
    session_id: Optional[str] = Form(None),
    product_category: Optional[str] = Form(None),
    angles: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)

    angles_list = None
    if angles:
        try:
            parsed = json.loads(angles)
            if isinstance(parsed, list):
                angles_list = [str(a) for a in parsed]
        except Exception:
            angles_list = [a.strip() for a in angles.split(",") if a.strip()]

    result = await PhotoshootService.upload_product_images(
        db=db,
        user_id=user_id,
        files=files,
        session_id=session_id,
        product_category=product_category,
        angles=angles_list,
    )
    return ProductUploadResponse(**result)


# ---------------------------------------------------------------------------
# 2. AI Product Visual Analysis
# ---------------------------------------------------------------------------
@router.post("/analyze", response_model=ProductAnalysisResponse, summary="Run visual multimodal inspection on uploaded product")
async def analyze_product(
    payload: ProductAnalysisRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)
    result = await PhotoshootService.analyze_product(
        db=db,
        user_id=user_id,
        session_id=payload.session_id,
        image_ids=payload.image_ids,
    )
    return ProductAnalysisResponse(**result)


# ---------------------------------------------------------------------------
# 3. AI Product Image Enhancement
# ---------------------------------------------------------------------------
@router.post("/enhance", response_model=ProductEnhanceResponse, summary="Generate studio, luxury, and marketplace enhancement variations")
async def enhance_product_images(
    payload: ProductEnhanceRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)
    result = await PhotoshootService.enhance_product_images(
        db=db,
        user_id=user_id,
        session_id=payload.session_id,
        image_id=payload.image_id,
        styles=payload.styles,
    )
    return ProductEnhanceResponse(**result)


# ---------------------------------------------------------------------------
# 3b. Select Enhanced Images
# ---------------------------------------------------------------------------
@router.post("/{session_id}/select-enhanced", summary="Mark specific enhanced images as active for final photoshoot")
async def select_enhanced_images(
    session_id: str,
    payload: SelectEnhancedRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)
    session_doc = await db["photoshoot_sessions"].find_one({"session_id": session_id, "user_id": user_id})
    if not session_doc:
        raise HTTPException(status_code=404, detail="Photoshoot session not found.")

    selected_set = set(payload.selected_image_ids)

    # Update session's enhanced_images list
    enhanced_list = session_doc.get("enhanced_images", [])
    for img in enhanced_list:
        img["is_selected"] = img.get("image_id") in selected_set

    await db["photoshoot_sessions"].update_one(
        {"session_id": session_id},
        {"$set": {"enhanced_images": enhanced_list}}
    )

    # Update photoshoot_images collection
    await db["photoshoot_images"].update_many(
        {"session_id": session_id, "user_id": user_id, "image_type": "enhanced"},
        {"$set": {"is_selected": False}}
    )
    if payload.selected_image_ids:
        await db["photoshoot_images"].update_many(
            {"session_id": session_id, "user_id": user_id, "image_id": {"$in": payload.selected_image_ids}},
            {"$set": {"is_selected": True}}
        )

    return {
        "success": True,
        "session_id": session_id,
        "selected_image_ids": payload.selected_image_ids,
        "message": "Enhanced product selection updated successfully."
    }


# ---------------------------------------------------------------------------
# 4. Curated AI Model Gallery
# ---------------------------------------------------------------------------
@router.get("/models", response_model=AIModelListResponse, summary="List curated AI fashion and product models")
async def get_models(
    gender: Optional[str] = Query(None, description="male, female, or unisex"),
    category: Optional[str] = Query(None, description="Clothing, Jewellery, Eyewear, etc."),
    current_user: dict = Depends(get_current_user),
):
    models = PhotoshootService.get_model_gallery(gender=gender, category=category)
    return AIModelListResponse(success=True, total=len(models), models=models)


# ---------------------------------------------------------------------------
# 5. Photography Styles & Poses Catalog
# ---------------------------------------------------------------------------
@router.get("/styles", response_model=PhotographyStylesResponse, summary="Get recommended styles and poses tailored to product & model mode")
async def get_styles(
    category: Optional[str] = Query(None, description="Product category hint"),
    use_model: bool = Query(False, description="Whether an AI model will be featured"),
    model_id: Optional[str] = Query(None, description="Selected AI model ID"),
    current_user: dict = Depends(get_current_user),
):
    styles = PhotoshootService.get_photography_styles(
        category=category,
        use_model=use_model,
        model_id=model_id,
    )
    return PhotographyStylesResponse(
        success=True,
        category=category or "All",
        use_model=use_model,
        styles=styles,
    )


# ---------------------------------------------------------------------------
# 6. Custom Prompt & Voice Instructions Preparation
# ---------------------------------------------------------------------------
@router.post("/prepare-prompt", response_model=PreparePromptResponse, summary="Synthesize prompt from styling, product, and instructions")
async def prepare_prompt_json(
    payload: PreparePromptRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)
    result = await PhotoshootService.prepare_prompt(
        db=db,
        user_id=user_id,
        session_id=payload.session_id,
        custom_prompt=payload.custom_prompt,
        language=payload.language or "en",
        use_model=bool(payload.use_model),
        model_id=payload.model_id,
        selected_styles=payload.selected_styles,
    )
    return PreparePromptResponse(**result)


@router.post("/prepare-prompt-audio", response_model=PreparePromptResponse, summary="Synthesize prompt with optional audio voice instruction")
async def prepare_prompt_audio(
    session_id: str = Form(...),
    custom_prompt: Optional[str] = Form(None),
    language: Optional[str] = Form("en"),
    use_model: bool = Form(False),
    model_id: Optional[str] = Form(None),
    selected_styles: Optional[str] = Form(None),
    audio_file: Optional[UploadFile] = File(None),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)
    styles_list = None
    if selected_styles:
        try:
            parsed = json.loads(selected_styles)
            if isinstance(parsed, list):
                styles_list = [str(s) for s in parsed]
        except Exception:
            styles_list = [s.strip() for s in selected_styles.split(",") if s.strip()]

    result = await PhotoshootService.prepare_prompt(
        db=db,
        user_id=user_id,
        session_id=session_id,
        custom_prompt=custom_prompt,
        language=language,
        use_model=use_model,
        model_id=model_id,
        selected_styles=styles_list,
        audio_file=audio_file,
    )
    return PreparePromptResponse(**result)


# ---------------------------------------------------------------------------
# 7. Final Photoshoot Generation & Job Status
# ---------------------------------------------------------------------------
@router.post("/generate", response_model=PhotoshootGenerateResponse, summary="Start unified photoshoot batch generation (model or product-only)")
async def generate_photoshoot(
    payload: PhotoshootGenerateRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)
    result = await PhotoshootService.start_photoshoot_generation(
        db=db,
        user_id=user_id,
        session_id=payload.session_id,
        selected_enhanced_image_ids=payload.selected_enhanced_image_ids,
        product_category=payload.product_category,
        use_model=payload.use_model,
        model_id=payload.model_id,
        selected_styles=payload.selected_styles,
        custom_prompt=payload.custom_prompt,
        image_count=payload.image_count,
    )
    return PhotoshootGenerateResponse(**result)


@router.get("/jobs/{job_id}", response_model=PhotoshootJobStatusResponse, summary="Poll progress of an async photoshoot generation job")
async def get_job_status(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)
    result = await PhotoshootService.get_job_status(db=db, user_id=user_id, job_id=job_id)
    return PhotoshootJobStatusResponse(**result)


@router.post("/jobs/{job_id}/retry", response_model=RetryJobResponse, summary="Retry only failed images from a partial or failed job")
async def retry_failed_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)
    result = await PhotoshootService.retry_failed_job_images(db=db, user_id=user_id, job_id=job_id)
    return RetryJobResponse(**result)


@router.get("/{session_id}/results", response_model=PhotoshootResultsResponse, summary="Get all generated photoshoot results for a session")
async def get_session_results(
    session_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)
    result = await PhotoshootService.get_session_results(db=db, user_id=user_id, session_id=session_id)
    return PhotoshootResultsResponse(**result)


# ---------------------------------------------------------------------------
# 8. Session Details, Gallery, Selection & Downloads
# ---------------------------------------------------------------------------
@router.get("/gallery", response_model=GalleryResponse, summary="Get paginated photoshoot sessions in user gallery")
async def get_gallery(
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=50),
    category: Optional[str] = Query(None),
    use_model: Optional[bool] = Query(None, description="Filter by AI model mode"),
    sort_by: Optional[str] = Query("desc", description="Sort order: 'desc' (newest first) or 'asc' (oldest first)"),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)
    result = await PhotoshootService.get_user_gallery(
        db=db,
        user_id=user_id,
        page=page,
        limit=limit,
        category=category,
        use_model=use_model,
        sort_by=sort_by,
    )
    return GalleryResponse(**result)


@router.get("/{session_id}", summary="Get detailed metadata for a single photoshoot session")
async def get_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)
    session_doc = await db["photoshoot_sessions"].find_one({"session_id": session_id, "user_id": user_id})
    if not session_doc:
        raise HTTPException(status_code=404, detail="Photoshoot session not found.")
    session_clean = _serialize_mongo(session_doc)
    # Ensure both uploaded_images and original_images are populated for client convenience
    if "original_images" in session_clean and "uploaded_images" not in session_clean:
        session_clean["uploaded_images"] = session_clean["original_images"]
    elif "uploaded_images" in session_clean and "original_images" not in session_clean:
        session_clean["original_images"] = session_clean["uploaded_images"]
    return {"success": True, "session": session_clean}


@router.post("/{session_id}/save", response_model=SaveImagesResponse, summary="Save selected photoshoot images to permanent user library")
async def save_selected_images(
    session_id: str,
    payload: SaveImagesRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)
    result = await PhotoshootService.save_selected_images(
        db=db,
        user_id=user_id,
        session_id=session_id,
        image_ids=payload.image_ids,
    )
    return SaveImagesResponse(**result)


@router.delete("/images/{image_id}", summary="Delete a photoshoot image asset")
async def delete_image(
    image_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)
    result = await PhotoshootService.delete_image(db=db, user_id=user_id, image_id=image_id)
    return result


@router.post("/images/{image_id}/regenerate", summary="Regenerate an individual photoshoot image with specific style")
async def regenerate_image(
    image_id: str,
    payload: Optional[RegenerateImageRequest] = None,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)
    style = payload.style if payload else None
    prompt = payload.custom_prompt if payload else None
    result = await PhotoshootService.regenerate_image(
        db=db,
        user_id=user_id,
        image_id=image_id,
        style=style,
        custom_prompt=prompt,
    )
    return result


@router.get("/images/{image_id}/download", summary="Download high-resolution image asset directly")
async def download_image(
    image_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)
    image_doc = await db["photoshoot_images"].find_one({"image_id": image_id, "user_id": user_id})
    if not image_doc:
        raise HTTPException(status_code=404, detail="Image not found or not owned by user.")

    rel_url = image_doc.get("url", "").lstrip("/")
    file_path = Path(rel_url)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found on disk.")

    filename = image_doc.get("filename") or f"{image_id}.jpg"
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=image_doc.get("content_type", "image/jpeg"),
    )


@router.get("/{session_id}/download", summary="Download ZIP archive of all saved/generated images for a session")
async def download_session_zip(
    session_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    user_id = _get_user_id(current_user)
    session_doc = await db["photoshoot_sessions"].find_one({"session_id": session_id, "user_id": user_id})
    if not session_doc:
        raise HTTPException(status_code=404, detail="Photoshoot session not found.")

    # Determine images to include: prioritize saved_image_ids, else all generated_images
    saved_ids = set(session_doc.get("saved_image_ids", []))
    gen_images = session_doc.get("generated_images", [])

    candidates = [img for img in gen_images if not saved_ids or img.get("image_id") in saved_ids]
    if not candidates and gen_images:
        candidates = gen_images

    if not candidates:
        raise HTTPException(status_code=404, detail="No generated images found to download in this session.")

    # Build ZIP archive in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, img in enumerate(candidates, start=1):
            rel_url = img.get("url", "").lstrip("/")
            file_path = Path(rel_url)
            if file_path.exists():
                arcname = f"photoshoot_{session_id}_{idx:02d}_{img.get('style_applied', 'style').replace(' ', '_')}.jpg"
                zf.write(file_path, arcname=arcname)

    zip_buffer.seek(0)
    zip_filename = f"dhandagrow_photoshoot_{session_id}.zip"

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )

