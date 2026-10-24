from typing import Optional
from fastapi import FastAPI, Request, Response, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import connect_to_mongo, close_mongo_connection, get_database
from app.services.scheduler_service import scheduler_service
from app.api.api_router import api_router
from app.api.endpoints import content, insights, messages, reviews, social
from app.api.endpoints.reel import router as reel_router, reels_router
from app.api.endpoints.credits import router as credits_router
from app.api.endpoints.festivals import router as festivals_router
from app.api.endpoints.agent import router as agent_router
from app.api.endpoints.fashion import router as fashion_router
from app.api.endpoints.instagram import router as instagram_router
from app.api.endpoints.facebook import router as facebook_router
from app.api.endpoints.linkedin import router as linkedin_router
from app.api.endpoints.brand import router as brand_router
from app.api.endpoints.influencers import router as influencers_router
from app.api.endpoints.influencer_profile import router as influencer_profile_router
from app.api.endpoints.business_collaborations import router as business_collaborations_router
from app.api.endpoints.influencer_content import router as influencer_content_router
from app.api.endpoints.influencer_earnings import router as influencer_earnings_router
from app.api.endpoints.influencer_marketplace import router as influencer_marketplace_router
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    connect_to_mongo()
    await scheduler_service.start()
    yield
    # Shutdown
    await scheduler_service.stop()
    close_mongo_connection()
from fastapi.staticfiles import StaticFiles
app = FastAPI(
    title="Dhanda Grow API",
    description="Backend API for Dhanda Grow Platform",
    version="1.0.0",
    lifespan=lifespan,
    swagger_ui_parameters={
        "filter": True,
        "docExpansion": "none",
        "displayRequestDuration": True,
        "persistAuthorization": True,
    },
)
import os
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
os.makedirs("media", exist_ok=True)
app.mount("/media", StaticFiles(directory="media"), name="media")
if os.path.exists("assets"):
    app.mount("/assets", StaticFiles(directory="assets"), name="assets")

# Set up CORS - works for localhost and all live deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS_LIST,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
app.include_router(api_router, prefix="/api/v1")
app.include_router(content.router)
app.include_router(social.router)
app.include_router(social.api_social_router, include_in_schema=False)
app.include_router(
    insights.router,
    prefix="/api/v1/insights",
    tags=["Insights"]
)
app.include_router(
    messages.router,
    prefix="/api/v1/messages",
    tags=["Messages"]
)
app.include_router(
    reviews.router,
    prefix="/api/v1/reviews",
    tags=["Reviews"]
)
app.include_router(reel_router)
app.include_router(reels_router)
app.include_router(credits_router)
app.include_router(festivals_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(fashion_router)
app.include_router(instagram_router, prefix="/api/instagram")
app.include_router(instagram_router, prefix="/api/v1/instagram")
app.include_router(facebook_router, prefix="/api/facebook")
app.include_router(facebook_router, prefix="/api/v1/facebook")
app.include_router(linkedin_router, prefix="/api/linkedin", include_in_schema=False)

# Preserved Root Social Media Callbacks & Webhooks for external provider redirects
from app.api.endpoints.instagram import (
    instagram_callback,
    webhook_verify as instagram_webhook_verify,
    webhook_receive as instagram_webhook_receive,
)

@app.get("/callback", tags=["Callbacks"], include_in_schema=False)
@app.get("/callback/", tags=["Callbacks"], include_in_schema=False)
async def root_oauth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_reason: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
    db=Depends(get_database),
):
    return await instagram_callback(
        request=request,
        code=code,
        state=state,
        error=error,
        error_reason=error_reason,
        error_description=error_description,
        db=db,
    )

@app.post("/callback", tags=["Callbacks"], include_in_schema=False)
async def root_webhook_callback(request: Request, db=Depends(get_database)):
    return await instagram_webhook_receive(request=request, db=db)

@app.get("/webhook", tags=["Callbacks"], include_in_schema=False)
async def root_webhook_verify(request: Request, db=Depends(get_database)):
    return await instagram_webhook_verify(request=request, db=db)

@app.post("/webhook", tags=["Callbacks"], include_in_schema=False)
async def root_webhook_receive(request: Request, db=Depends(get_database)):
    return await instagram_webhook_receive(request=request, db=db)
app.include_router(brand_router, prefix="/api/brands", tags=["Brand Kit"], include_in_schema=False)
app.include_router(influencers_router, prefix="/api/v1")
app.include_router(influencer_profile_router, prefix="/api/v1")
app.include_router(business_collaborations_router, prefix="/api/v1")
app.include_router(influencer_content_router, prefix="/api/v1")
app.include_router(influencer_earnings_router, prefix="/api/v1")
app.include_router(influencer_marketplace_router, prefix="/api/v1")
@app.get("/")
async def root():
    return {"message": "Welcome to Dhanda Grow API"}


@app.get("/health")
@app.get("/api/v1/health")
async def health():
    return {"status": "healthy", "service": "Dhanda Grow API"}


from fastapi.responses import JSONResponse
from fastapi import Request
import traceback
import sys

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print("GLOBAL EXCEPTION:", exc, file=sys.stderr)
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "error": str(exc), "traceback": traceback.format_exc()}
    )

# reload trigger 7

# reload trigger 8
