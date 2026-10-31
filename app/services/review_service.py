from datetime import datetime, timezone
from bson import ObjectId
from fastapi import HTTPException
import logging
from app.schemas.review import ReviewCreate, ReviewUpdate

logger = logging.getLogger(__name__)

def serialize_review(rev):
    created_at = rev.get("created_at")
    if hasattr(created_at, "isoformat"):
        created_at_str = created_at.isoformat()
    else:
        created_at_str = str(created_at or "")

    updated_at = rev.get("updated_at")
    if hasattr(updated_at, "isoformat"):
        updated_at_str = updated_at.isoformat()
    else:
        updated_at_str = str(updated_at or "")

    review_id = str(rev["_id"])
    customer_name = rev.get("customer_name") or rev.get("customerName", "Customer")
    review_text = rev.get("review_text") or rev.get("reviewText", "")
    rating = rev.get("rating", 5)
    status = rev.get("status", "Pending")
    reply = rev.get("reply")

    return {
        "_id": review_id,
        "id": review_id,
        "business_id": str(rev.get("business_id", "")),
        "customerName": customer_name,
        "customer_name": customer_name,
        "rating": rating,
        "reviewText": review_text,
        "review_text": review_text,
        "status": status,
        "reply": reply,
        "createdAt": created_at_str,
        "created_at": created_at_str,
        "updatedAt": updated_at_str,
        "updated_at": updated_at_str,
    }

async def create_review(db, business_id: str, data: ReviewCreate):
    collection = db["reviews"]
    rev_data = data.model_dump(exclude_none=True)
    now = datetime.now(timezone.utc)
    
    b_id = ObjectId(business_id) if ObjectId.is_valid(business_id) else business_id
    rev_data["business_id"] = b_id
    rev_data["created_at"] = now
    rev_data["updated_at"] = now
    
    result = await collection.insert_one(rev_data)
    rev = await collection.find_one({"_id": result.inserted_id})
    return serialize_review(rev)

async def get_reviews(db, business_id: str):
    collection = db["reviews"]
    query = {}
    if ObjectId.is_valid(business_id):
        query = {"business_id": ObjectId(business_id)}
    else:
        query = {"business_id": business_id}

    cursor = collection.find(query).sort("created_at", -1)
    reviews = []
    async for rev in cursor:
        reviews.append(serialize_review(rev))
        
    return reviews

async def get_review(db, business_id: str, review_id: str):
    if not ObjectId.is_valid(review_id):
        raise HTTPException(status_code=400, detail="Invalid review ID")
        
    rev = await db["reviews"].find_one({"_id": ObjectId(review_id)})
    if not rev:
        raise HTTPException(status_code=404, detail="Review not found")
        
    return serialize_review(rev)

async def update_review(db, business_id: str, review_id: str, data: ReviewUpdate):
    if not ObjectId.is_valid(review_id):
        raise HTTPException(status_code=400, detail="Invalid review ID")
        
    update_data = data.model_dump(exclude_none=True)
    existing = await db["reviews"].find_one({"_id": ObjectId(review_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Review not found")
        
    update_data["updated_at"] = datetime.now(timezone.utc)
    
    await db["reviews"].update_one(
        {"_id": ObjectId(review_id)},
        {"$set": update_data}
    )
    
    updated = await db["reviews"].find_one({"_id": ObjectId(review_id)})
    return serialize_review(updated)

async def delete_review(db, business_id: str, review_id: str):
    if not ObjectId.is_valid(review_id):
        raise HTTPException(status_code=400, detail="Invalid review ID")
        
    result = await db["reviews"].delete_one({"_id": ObjectId(review_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Review not found")
        
    return {"success": True, "message": "Review deleted successfully"}

async def generate_sample_reviews(db, business_id: str, count: int = 4):
    return await _generate_sample_reviews_impl(db, business_id, count)

generate_sample_reviews_gemini = generate_sample_reviews

async def _generate_sample_reviews_impl(db, business_id: str, count: int = 4):
    """
    Uses OpenAI API to generate authentic, realistic Google Reviews tailored to the business.
    """
    from app.ai.factory import AIProviderFactory
    import json
    import re

    business = None
    if ObjectId.is_valid(business_id):
        business = await db["businesses"].find_one({"_id": ObjectId(business_id)})
    if not business:
        business = await db["businesses"].find_one({"owner_id": business_id})

    biz_name = business.get("name", "Our Business") if business else "Our Store"
    biz_category = business.get("category", "Retail & Services") if business else "Retail"

    prompt = f"""You are a realistic customer review generator for Google Reviews and Google Maps.
Generate {count} realistic, authentic, and diverse customer reviews for the following business:
Business Name: {biz_name}
Business Category: {biz_category}

Guidelines:
- Authentic Names: Use realistic, culturally appropriate names (mix of Indian and global names, e.g. Ananya Sharma, Rajesh Patel, Emily Carter, Vikram Malhotra, Priya Mehta).
- Realistic Ratings: Provide a realistic distribution (e.g. 5-star, 4-star, and one constructive 3-star).
- Detailed Feedback: Write realistic reviews detailing their customer experience, product quality, ambiance, delivery or customer service.
- Status: Set status to "Pending".

Output ONLY valid raw JSON with this schema (no markdown, no ```json code fences):
{{
  "reviews": [
    {{
      "customer_name": "Customer Name",
      "rating": 5,
      "review_text": "Detailed realistic customer review...",
      "status": "Pending"
    }}
  ]
}}"""

    ai_provider = AIProviderFactory.get_provider("openai")
    try:
        res = await ai_provider.generate_text(
            prompt=prompt,
            system_prompt="You are an expert customer feedback analyst. Output only raw JSON with no markdown.",
            max_tokens=2048
        )
        raw = res.get("text", "{}").strip()
        raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        
        if "`" in raw:
            parts = raw.split("`")
            for part in parts:
                cleaned = part.strip()
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:].strip()
                if cleaned.startswith("{"):
                    raw = cleaned
                    break

        first_b = raw.find("{")
        last_b = raw.rfind("}")
        if first_b != -1 and last_b != -1:
            raw = raw[first_b:last_b+1]

        data = json.loads(raw)
        created_reviews = []
        now = datetime.now(timezone.utc)
        target_b_id = ObjectId(business_id) if ObjectId.is_valid(business_id) else business_id

        for item in data.get("reviews", []):
            doc = {
                "business_id": target_b_id,
                "customer_name": item.get("customer_name", "Valued Customer"),
                "rating": item.get("rating", 5),
                "review_text": item.get("review_text", "Great experience!"),
                "status": "Pending",
                "reply": None,
                "created_at": now,
                "updated_at": now
            }
            result = await db["reviews"].insert_one(doc)
            doc["_id"] = result.inserted_id
            created_reviews.append(serialize_review(doc))

        logger.info(f"Generated {len(created_reviews)} reviews with OpenAI for business {business_id}")
        return created_reviews

    except Exception as e:
        logger.error(f"OpenAI failed to generate reviews: {e}")
        return []

async def generate_ai_reply(db, business_id: str, review_id: str, custom_data: dict = None):
    """
    Uses OpenAI API to generate an empathetic, professional, personalized reply to a customer review.
    """
    from app.ai.factory import AIProviderFactory
    import re

    rev = None
    if ObjectId.is_valid(review_id):
        rev = await db["reviews"].find_one({"_id": ObjectId(review_id)})

    if not rev and custom_data:
        rev = custom_data

    rating = rev.get("rating", 5) if rev else 5
    review_text = rev.get("review_text") or rev.get("reviewText", "") if rev else ""
    customer_name = rev.get("customer_name") or rev.get("customerName", "Customer") if rev else "Customer"

    # Business context
    biz = None
    if ObjectId.is_valid(business_id):
        biz = await db["businesses"].find_one({"_id": ObjectId(business_id)})
    if not biz:
        biz = await db["businesses"].find_one({"owner_id": business_id})
    biz_name = biz.get("name", "our team") if biz else "our team"

    prompt = f"""You are the friendly, professional customer experience manager at {biz_name}.
Write an authentic, warm, and personalized reply to the following Google Review.

Customer Name: {customer_name}
Rating: {rating}/5 Stars
Review: "{review_text}"

Guidelines:
- If 4 or 5 stars: Genuinely thank {customer_name}, mention specific details they enjoyed, and express warm appreciation.
- If 1, 2, or 3 stars: Apologize with empathy and sincerity, address their specific concern, and offer a polite resolution route (e.g., inviting them to connect with store management to make it right).
- Tone: Professional, courteous, warm, and natural.
- Output ONLY the reply text directly. Do NOT include quotes, placeholders, or explanations.
"""

    ai_provider = AIProviderFactory.get_provider("openai")
    try:
        response = await ai_provider.generate_text(
            prompt=prompt,
            system_prompt="You are an expert customer service director. Write authentic, personalized Google review replies directly without quotes.",
            max_tokens=512
        )
        reply = response.get("text", "").strip()
        reply = re.sub(r'<think>.*?</think>', '', reply, flags=re.DOTALL).strip()
        if reply.startswith('"') and reply.endswith('"'):
            reply = reply[1:-1].strip()
        return reply
    except Exception as e:
        logger.error(f"OpenAI failed to generate review reply: {e}")
        if rating >= 4:
            return f"Thank you so much for your valuable feedback, {customer_name}! We're thrilled you had a great experience and look forward to serving you again."
        else:
            return f"We're truly sorry you had this experience, {customer_name}. Please reach out to us directly so our team can resolve this for you."
