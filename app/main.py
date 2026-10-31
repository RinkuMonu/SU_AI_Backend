from typing import Optional
from bson import ObjectId
from fastapi import FastAPI, Request, Response
from fastapi.encoders import ENCODERS_BY_TYPE
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Register ObjectId serialization globally so jsonable_encoder never throws 500 on MongoDB ObjectIds
ENCODERS_BY_TYPE[ObjectId] = str
# Reload trigger 10
from app.core.config import settings
from app.core.database import connect_to_mongo, close_mongo_connection, init_db_indexes
from app.services.scheduler_service import scheduler_service
from app.api.api_router import api_router
from app.api.endpoints import content, insights, messages, reviews, social
from app.api.endpoints.reel import router as reel_router, reels_router
from app.api.endpoints.credits import router as credits_router
from app.api.endpoints.subscription import router as subscription_router
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
from app.api.endpoints.payments import router as payments_router
from app.api.endpoints.transactions import router as transactions_router
from app.api.endpoints.influencer_marketplace import router as influencer_marketplace_router
from app.api.endpoints.leads import router as leads_router
from app.api.endpoints.photoshoot import router as photoshoot_router
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    connect_to_mongo()
    await init_db_indexes()
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
)
import os
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
os.makedirs("media", exist_ok=True)
app.mount("/media", StaticFiles(directory="media"), name="media")
if os.path.exists("assets"):
    app.mount("/assets", StaticFiles(directory="assets"), name="assets")

from pymongo.errors import PyMongoError
from fastapi.responses import JSONResponse

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


@app.exception_handler(PyMongoError)
async def pymongo_exception_handler(request: Request, exc: PyMongoError):
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Database connection error. Please verify MongoDB network access and IP whitelist in Atlas.",
            "code": "DATABASE_UNAVAILABLE",
            "error": str(exc)[:200]
        }
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
app.include_router(subscription_router)
app.include_router(festivals_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(fashion_router)
app.include_router(instagram_router, prefix="/api/instagram")
app.include_router(instagram_router, prefix="/api/v1/instagram")
app.include_router(facebook_router, prefix="/api/facebook")
app.include_router(facebook_router, prefix="/api/v1/facebook")
app.include_router(linkedin_router, prefix="/api/linkedin", include_in_schema=False)
app.include_router(brand_router, prefix="/api/brands", tags=["Brand Kit"], include_in_schema=False)
app.include_router(brand_router, prefix="/api/brand", tags=["Brand Kit"], include_in_schema=False)
app.include_router(brand_router, prefix="/api/brand-kit", tags=["Brand Kit"], include_in_schema=False)
app.include_router(brand_router, prefix="/brand-kit", tags=["Brand Kit"], include_in_schema=False)
app.include_router(brand_router, prefix="/brand", tags=["Brand Kit"], include_in_schema=False)
app.include_router(payments_router, prefix="/api/payments", tags=["payments"], include_in_schema=False)
app.include_router(payments_router, prefix="/payments", tags=["payments"], include_in_schema=False)
app.include_router(transactions_router, prefix="/api/transactions", include_in_schema=False)
app.include_router(transactions_router, prefix="/transactions", include_in_schema=False)
app.include_router(influencers_router, prefix="/api/v1")
app.include_router(influencer_profile_router, prefix="/api/v1")
app.include_router(business_collaborations_router, prefix="/api/v1")
app.include_router(influencer_content_router, prefix="/api/v1")
app.include_router(influencer_earnings_router, prefix="/api/v1")
app.include_router(influencer_marketplace_router, prefix="/api/v1")
app.include_router(leads_router, prefix="/api/leads", include_in_schema=False)
app.include_router(leads_router, prefix="/api/contact", include_in_schema=False)
app.include_router(leads_router, prefix="/leads", include_in_schema=False)
app.include_router(leads_router, prefix="/contact", include_in_schema=False)
app.include_router(photoshoot_router, prefix="/product-photoshoot", include_in_schema=False)
app.include_router(photoshoot_router, prefix="/api/product-photoshoot", include_in_schema=False)
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
