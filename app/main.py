from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import connect_to_mongo, close_mongo_connection
from app.services.scheduler_service import scheduler_service
from app.api.api_router import api_router
from app.api.endpoints.brand import router as brand_router
from app.api.endpoints.products import router as products_router
from app.api.endpoints import content, insights, messages, reviews, social
from app.api.endpoints.ad import router as ad_router
from app.api.endpoints.reel import router as reel_router
from app.api.endpoints.credits import router as credits_router
from app.api.endpoints.subscription import router as subscription_router
from app.api.endpoints.festivals import router as festivals_router
from app.api.endpoints.agent import router as agent_router
from app.api.endpoints.fashion import router as fashion_router
from app.api.endpoints.instagram import router as instagram_router
from app.api.endpoints.facebook import router as facebook_router
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
    title="SevenUnique AI API",
    description="Backend API for SevenUnique AI Marketing Platform",
    version="1.0.0",
    lifespan=lifespan,
)
import os
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
# Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS_LIST,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api/v1")
app.include_router(content.router)
app.include_router(social.router)
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
app.include_router(ad_router)
app.include_router(reel_router)
app.include_router(credits_router)
app.include_router(subscription_router)
app.include_router(festivals_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(fashion_router)
app.include_router(instagram_router)
app.include_router(facebook_router)
app.include_router(influencers_router, prefix="/api/v1")
app.include_router(influencer_profile_router, prefix="/api/v1")
app.include_router(business_collaborations_router, prefix="/api/v1")
app.include_router(influencer_content_router, prefix="/api/v1")
app.include_router(influencer_earnings_router, prefix="/api/v1")
app.include_router(influencer_marketplace_router, prefix="/api/v1")
@app.get("/")
async def root():
    return {"message": "Welcome to SevenUnique AI API"}
