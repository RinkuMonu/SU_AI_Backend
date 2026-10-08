import json
import logging
from app.ai.factory import AIProviderFactory
from app.ai.prompts.reel import get_reel_script_prompt
from app.schemas.reel import ReelScript

logger = logging.getLogger(__name__)

class ReelScriptService:
    def __init__(self):
        self.provider = AIProviderFactory.get_provider()

    async def generate_script(
        self,
        product: dict,
        brand: dict,
        objective: str,
        platform: str,
        duration: int,
        language: str,
        tone: str,
        offer: str = None,
        additional_instruction: str = None
    ) -> ReelScript:
        prompt = get_reel_script_prompt(
            product=product,
            brand=brand,
            objective=objective,
            platform=platform,
            duration=duration,
            language=language,
            tone=tone,
            offer=offer,
            additional_instruction=additional_instruction
        )
        
        system_prompt = "You are a professional AI video script writer. Output only valid JSON."
        
        try:
            response = await self.provider.generate_text(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.7,
                response_format={"type": "json_object"},
                max_tokens=3000
            )
            
            content = response.get("text", "")
            
            # Safe JSON parsing
            try:
                parsed_json = json.loads(content)
            except json.JSONDecodeError:
                # Attempt to extract JSON from markdown if the model hallucinated formatting
                import re
                json_match = re.search(r'```(?:json)?(.*?)```', content, re.DOTALL)
                if json_match:
                    parsed_json = json.loads(json_match.group(1).strip())
                else:
                    raise ValueError("Failed to parse JSON from AI response.")
                    
            # Validate with Pydantic
            script = ReelScript(**parsed_json)
            return script
            
        except Exception as e:
            logger.error(f"Error generating reel script: {e}")
            raise e
