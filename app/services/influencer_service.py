from bson import ObjectId
from datetime import datetime, timezone
from app.core.database import get_database
from app.models.influencer import Influencer, InfluencerCampaign
from app.services.business_service import BusinessService
from app.ai.factory import AIProviderFactory
import uuid

class InfluencerService:
    @staticmethod
    async def get_influencer_collection():
        db = get_database()
        return db["influencers"]

    @staticmethod
    async def get_campaign_collection():
        db = get_database()
        return db["influencer_campaigns"]

    @staticmethod
    async def seed_mock_influencers():
        # Seed some dummy influencers if empty for discovery
        collection = await InfluencerService.get_influencer_collection()
        count = await collection.count_documents({})
        if count == 0:
            mock_data = [
                {"name": "TechGuru Max", "platform": "YouTube", "niche": "Tech", "followers_count": 500000, "engagement_rate": 5.2, "contact_email": "max@example.com"},
                {"name": "Style By Sarah", "platform": "Instagram", "niche": "Fashion", "followers_count": 120000, "engagement_rate": 3.8, "contact_email": "sarah@example.com"},
                {"name": "Foodie Frank", "platform": "Instagram", "niche": "Food", "followers_count": 85000, "engagement_rate": 4.1, "contact_email": "frank@example.com"},
                {"name": "Fitness Jane", "platform": "Instagram", "niche": "Fitness", "followers_count": 210000, "engagement_rate": 6.5, "contact_email": "jane@example.com"}
            ]
            for doc in mock_data:
                doc["created_at"] = datetime.now(timezone.utc)
            await collection.insert_many(mock_data)

    @staticmethod
    async def discover_influencers(business_id: str):
        await InfluencerService.seed_mock_influencers()
        collection = await InfluencerService.get_influencer_collection()
        
        # In a real app, match based on business niche. For now, return all.
        cursor = collection.find({}).sort("followers_count", -1)
        influencers = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            influencers.append(doc)
        return influencers

    @staticmethod
    async def add_influencer(data: dict):
        collection = await InfluencerService.get_influencer_collection()
        data["created_at"] = datetime.now(timezone.utc)
        res = await collection.insert_one(data)
        data["id"] = str(res.inserted_id)
        data.pop("_id", None)
        return data

    @staticmethod
    async def generate_pitch(business_id: str, influencer_id: str, user_id: str) -> str:
        db = get_database()
        business = await BusinessService.get_business_by_owner(user_id)
        if not business:
            raise Exception("Business not found")
            
        inf_col = await InfluencerService.get_influencer_collection()
        influencer = await inf_col.find_one({"_id": ObjectId(influencer_id)})
        if not influencer:
            raise Exception("Influencer not found")
            
        ai = AIProviderFactory.get_provider()
        prompt = f"Generate a collaboration pitch message to an influencer named {influencer['name']} in the {influencer['niche']} niche on {influencer['platform']}. You represent the business '{business.name}' which is in the '{business.category}' category. Keep the message friendly, professional, short, and propose a collaboration or product review."
        
        result = await ai.generate_text(prompt, system_prompt="You are an expert PR and marketing manager writing influencer outreach DMs.")
        
        return result.get("text", "Hey! Would love to collaborate with you.")
        
    @staticmethod
    async def create_campaign(business_id: str, influencer_id: str, message: str, budget: float = 0):
        collection = await InfluencerService.get_campaign_collection()
        campaign = {
            "business_id": business_id,
            "influencer_id": influencer_id,
            "status": "pending",
            "ai_pitch_message": message,
            "budget": budget,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        res = await collection.insert_one(campaign)
        campaign["id"] = str(res.inserted_id)
        campaign.pop("_id", None)
        return campaign
        
    @staticmethod
    async def get_campaigns(business_id: str):
        collection = await InfluencerService.get_campaign_collection()
        cursor = collection.find({"business_id": business_id}).sort("created_at", -1)
        campaigns = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            campaigns.append(doc)
        return campaigns
