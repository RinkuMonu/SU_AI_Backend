from typing import Dict, Any
import asyncio
from app.ai.base import AIProvider

class MockAIProvider(AIProvider):
    """
    A mock provider for development and testing.
    Returns deterministic structured text data or conversational text based on request format.
    """
    
    async def generate_text(self, prompt: str, system_prompt: str = None, **kwargs) -> Dict[str, Any]:
        # Simulate network delay
        await asyncio.sleep(0.5)
        
        response_format = kwargs.get("response_format", {})
        is_json = response_format.get("type") == "json_object"
        
        if is_json or "Return ONLY valid JSON" in prompt or "marketing post" in prompt or "headline" in prompt:
            import json
            if "THREE website design recommendations" in prompt:
                mock_response = {
                    "recommendations": [
                        {"id": "rec1", "name": "Premium Luxury", "description": "High end look", "reason": "Fits your brand", "palette": "Black/Gold", "style": "Luxury"},
                        {"id": "rec2", "name": "Modern Minimal", "description": "Clean look", "reason": "Contemporary style", "palette": "Blue/White", "style": "Minimal"},
                        {"id": "rec3", "name": "Vibrant Casual", "description": "Energetic", "reason": "Attracts youth", "palette": "Orange/Yellow", "style": "Bold"}
                    ]
                }
            elif "structured website JSON representation" in prompt:
                mock_response = {
                    "pages": [
                        {"home": {"hero": "Welcome!", "features": []}},
                        {"about": {"content": "About us section..."}}
                    ],
                    "theme": {"primary": "#000000"}
                }
            elif "Extract structured fields" in prompt:
                mock_response = {
                    "Business Name": "Sharma Fashion",
                    "Business Category": "Clothing"
                }
            elif "marketing post" in prompt or "Return ONLY valid JSON" in prompt or "headline" in prompt:
                mock_response = {
                    "headline": "Elevate Your Business With Premium Quality",
                    "caption": "Experience unmatched quality and professional excellence tailored to help your brand grow and stand out in the marketplace. Connect with us to explore more!",
                    "call_to_action": "Shop Now / Learn More",
                    "hashtags": ["#BusinessGrowth", "#SpecialOffer", "#Trending", "#DhandaGrow"],
                    "creative_direction": "Sleek, vibrant product showcase with balanced modern lighting"
                }
            else:
                mock_response = {
                    "caption": "Experience premium quality with our latest collection.",
                    "hashtags": ["#PremiumQuality", "#Fashion"],
                    "cta": "Shop Now"
                }
            text_content = json.dumps(mock_response)
        else:
            text_content = "Got it! Thanks for the information. Based on this, would you like me to recommend some templates for your website, or should we go ahead and build it?"

        return {
            "text": text_content,
            "metadata": {
                "provider": "mock",
                "model": "mock-model-v1",
                "usage": {
                    "prompt_tokens": len(prompt) // 4,
                    "completion_tokens": len(text_content) // 4,
                    "total_tokens": (len(prompt) + len(text_content)) // 4
                }
            }
        }
