from fastapi import APIRouter
from app.api.endpoints import (
    ai,
    auth,
    campaigns,
    admin,
    analytics,
    website_builder,
    subscription,
    payments,
    onboarding,
    users,
    businesses,
    linkedin,
    brand,
    leads,
    transactions,
    photoshoot,
)

api_router = APIRouter()
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(campaigns.router)
api_router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
api_router.include_router(website_builder.router, prefix="/website-builder", tags=["website-builder"])
api_router.include_router(subscription.router)
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(transactions.router, prefix="/transactions", tags=["Transactions"])
api_router.include_router(photoshoot.router, prefix="/product-photoshoot", tags=["Product Photoshoot Studio"])
api_router.include_router(onboarding.router, prefix="/onboarding", tags=["onboarding"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(businesses.router, prefix="/businesses", tags=["Businesses"])
api_router.include_router(brand.router, prefix="/brands", tags=["Brand Kit"])
api_router.include_router(linkedin.router, prefix="/linkedin", tags=["LinkedIn"])
api_router.include_router(leads.router, prefix="/leads", tags=["Leads"])
api_router.include_router(leads.router, prefix="/contact", tags=["Contact"], include_in_schema=False)
