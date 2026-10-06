from bson import ObjectId
from datetime import datetime, timezone
from app.core.database import get_database
from app.services.business_service import BusinessService
from app.ai.factory import AIProviderFactory
from typing import List, Dict, Any, Optional

class InfluencerService:
    @staticmethod
    async def get_influencer_profile_collection():
        db = get_database()
        return db["influencer_profiles"]

    @staticmethod
    async def get_campaign_collection():
        db = get_database()
        return db["influencer_campaigns"]

    @staticmethod
    async def get_shortlist_collection():
        db = get_database()
        return db["influencer_shortlists"]

    @staticmethod
    async def calculate_ai_match_score(business: dict, influencer: dict) -> dict:
        """
        Calculates an AI Match Score based on business and influencer profiles.
        Returns a dict with 'score' (0-100) and 'explanation'.
        """
        ai = AIProviderFactory.get_provider()
        business_cat = business.get("category", "Unknown")
        business_aud = business.get("target_audience", "General")
        
        inf_cat = influencer.get("category", "Unknown")
        inf_foll = influencer.get("follower_count", 0)
        inf_eng = influencer.get("engagement_rate", 0.0)
        
        prompt = f"""
        Analyze the match between this business and influencer for a campaign:
        Business Category: {business_cat}
        Business Target Audience: {business_aud}
        
        Influencer Category: {inf_cat}
        Influencer Followers: {inf_foll}
        Influencer Engagement Rate: {inf_eng}%
        
        Provide a JSON response with exactly two keys:
        - "score": an integer from 0 to 100 representing how good the match is.
        - "explanation": a short 2-3 sentence explanation of why this score was given.
        
        Do not fabricate any extra data. Base it strictly on these inputs.
        """
        
        try:
            # Assumes the AI provider can return structured data or we parse JSON
            result = await ai.generate_text(prompt, system_prompt="You are an expert influencer marketing AI. Reply ONLY in valid JSON format with 'score' and 'explanation' keys.", is_json=True)
            
            import json
            # Fallback parsing in case the AI provider returns text with markdown
            text_result = result.get("text", "{}")
            if text_result.startswith("```json"):
                text_result = text_result.split("```json")[1].split("```")[0].strip()
            elif text_result.startswith("```"):
                text_result = text_result.split("```")[1].strip()
                
            parsed = json.loads(text_result)
            return {
                "score": parsed.get("score", 70),
                "explanation": parsed.get("explanation", "Match generated based on category and engagement.")
            }
        except Exception as e:
            return {
                "score": 0,
                "explanation": "Could not generate match score due to AI service error."
            }

    @staticmethod
    async def discover_influencers(business_id: str, filters: dict = None) -> List[dict]:
        collection = await InfluencerService.get_influencer_profile_collection()
        
        # Build query from filters
        query = {}
        if filters:
            if filters.get("category"):
                query["category"] = {"$regex": filters["category"], "$options": "i"}
            if filters.get("min_followers"):
                query["follower_count"] = {"$gte": int(filters["min_followers"])}
            if filters.get("location"):
                query["location"] = {"$regex": filters["location"], "$options": "i"}
            if filters.get("platform"):
                # Check socials
                platform = filters["platform"].lower()
                if platform == "instagram":
                    query["instagram_url"] = {"$ne": None}
                elif platform == "youtube":
                    query["youtube_url"] = {"$ne": None}
        
        cursor = collection.find(query).sort("follower_count", -1).limit(50)
        
        db = get_database()
        business = await db["businesses"].find_one({"_id": ObjectId(business_id)})
        
        influencers = []
        async for doc in cursor:
            doc["id"] = doc.get("user_id", str(doc["_id"]))
            doc.pop("_id", None)
            
            # Generate AI match score if business exists
            if business:
                match_data = await InfluencerService.calculate_ai_match_score(business, doc)
                doc["ai_match_score"] = match_data["score"]
                doc["ai_match_explanation"] = match_data["explanation"]
                
            influencers.append(doc)
            
        return influencers

    @staticmethod
    async def generate_pitch(business_id: str, influencer_id: str, user_id: str, style: str = "Professional") -> str:
        db = get_database()
        business = await BusinessService.get_business_by_owner(user_id)
        if not business:
            raise Exception("Business not found")
            
        inf_col = await InfluencerService.get_influencer_profile_collection()
        influencer = await inf_col.find_one({"user_id": influencer_id})
        
        inf_name = influencer.get("username", "Creator") if influencer else "Creator"
        inf_cat = influencer.get("category", "content") if influencer else "content"
            
        ai = AIProviderFactory.get_provider()
        prompt = f"Generate a {style} collaboration pitch message to an influencer named {inf_name} in the {inf_cat} niche. You represent the business '{business.name}' which is in the '{business.category}' category. Keep the message friendly, concise, and propose a collaboration or product review."
        
        result = await ai.generate_text(prompt, system_prompt="You are an expert PR and marketing manager writing influencer outreach DMs.")
        
        return result.get("text", "Hey! Would love to collaborate with you.")
        
    @staticmethod
    async def create_campaign(business_id: str, influencer_id: str, message: str, budget: float = 0, deliverables: List[str] = None):
        collection = await InfluencerService.get_campaign_collection()
        campaign = {
            "business_id": business_id,
            "influencer_id": influencer_id,
            "status": "pending",
            "ai_pitch_message": message,
            "budget": budget,
            "deliverables": deliverables or [],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        res = await collection.insert_one(campaign)
        campaign["id"] = str(res.inserted_id)
        campaign.pop("_id", None)
        return campaign
        
    @staticmethod
    async def get_campaigns(business_id: str):
        db = get_database()
        collection = await InfluencerService.get_campaign_collection()
        cursor = collection.find({"business_id": business_id}).sort("created_at", -1)
        
        campaigns = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            
            # Fetch influencer profile for display
            from bson import ObjectId
            
            inf = None
            if ObjectId.is_valid(doc["influencer_id"]):
                # Try finding by exact _id first
                inf = await db["influencer_profiles"].find_one({"_id": ObjectId(doc["influencer_id"])})
                
            if not inf:
                # Fallback to finding by user_id
                inf = await db["influencer_profiles"].find_one({"user_id": doc["influencer_id"]})
                
            if inf:
                doc["influencer_name"] = inf.get("username") or inf.get("name") or "Unknown Creator"
                doc["influencer_image"] = inf.get("profile_image", "")
            else:
                doc["influencer_name"] = "Unknown Creator"
                
            # Determine Pipeline Status
            pipeline_status = "Contacted" # Base status
            if doc.get("status") == "applied":
                pipeline_status = "Negotiating"
                
            # Check for application
            app = await db["campaign_applications"].find_one({
                "campaign_id": doc["id"],
                "influencer_id": doc["influencer_id"]
            })
            if app and app.get("status") == "rejected":
                pipeline_status = "Rejected"
                
            # Check for active collaboration
            collab = await db["collaborations"].find_one({
                "campaign_id": doc["id"],
                "influencer_id": doc["influencer_id"]
            })
            if collab:
                collab_status = collab.get("status", "active")
                if collab_status == "active":
                    pipeline_status = "Accepted"
                elif collab_status == "content_submitted":
                    pipeline_status = "Content Pending Review"
                elif collab_status == "changes_requested":
                    pipeline_status = "Revision Requested"
                elif collab_status == "approved":
                    pipeline_status = "Content Approved"
                elif collab_status == "published":
                    pipeline_status = "Published"
                elif collab_status == "completed":
                    pipeline_status = "Completed"
                    
            doc["pipeline_status"] = pipeline_status
            campaigns.append(doc)
            
        return campaigns

    @staticmethod
    async def toggle_shortlist(business_id: str, influencer_id: str):
        collection = await InfluencerService.get_shortlist_collection()
        existing = await collection.find_one({"business_id": business_id, "influencer_id": influencer_id})
        
        if existing:
            await collection.delete_one({"_id": existing["_id"]})
            return {"shortlisted": False}
        else:
            await collection.insert_one({
                "business_id": business_id,
                "influencer_id": influencer_id,
                "created_at": datetime.now(timezone.utc)
            })
            return {"shortlisted": True}

    @staticmethod
    async def get_shortlist(business_id: str):
        collection = await InfluencerService.get_shortlist_collection()
        cursor = collection.find({"business_id": business_id}).sort("created_at", -1)
        
        inf_col = await InfluencerService.get_influencer_profile_collection()
        
        results = []
        async for doc in cursor:
            inf = await inf_col.find_one({"user_id": doc["influencer_id"]})
            if inf:
                inf["id"] = inf.get("user_id", str(inf["_id"]))
                inf.pop("_id", None)
                doc["influencer"] = inf
                
            doc["id"] = str(doc.pop("_id"))
            results.append(doc)
            
        return results
