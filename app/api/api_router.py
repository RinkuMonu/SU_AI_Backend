from fastapi import APIRouter
from app.api.endpoints import ai, auth, campaigns, admin, analytics, website_builder, subscription, payments, onboarding

api_router = APIRouter()
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(campaigns.router)
api_router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
api_router.include_router(website_builder.router, prefix="/website-builder", tags=["website-builder"])
api_router.include_router(subscription.router)
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(onboarding.router, prefix="/onboarding", tags=["onboarding"])
