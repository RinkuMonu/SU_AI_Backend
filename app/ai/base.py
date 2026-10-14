from abc import ABC, abstractmethod
from typing import Dict, Any

class AIProvider(ABC):
    """
    Abstract base class for all AI providers.
    Ensures that the rest of the application remains independent of the specific AI provider.
    """
    
    @abstractmethod
    async def generate_text(self, prompt: str, system_prompt: str = None, **kwargs) -> Dict[str, Any]:
        """
        Generates text based on the given prompt.
        
        Args:
            prompt: The main user prompt.
            system_prompt: Optional system instructions.
            **kwargs: Additional provider-specific arguments (temperature, max_tokens, etc).
            
        Returns:
            A dictionary containing the generated text and any metadata (like usage).
        """
        pass
    
    async def generate_json(self, prompt: str, system_prompt: str = None, **kwargs) -> Dict[str, Any]:
        """
        Convenience method to generate text and parse it as JSON.
        """
        import json
        import re
        
        # Suggest JSON output format
        kwargs["response_format"] = {"type": "json_object"}
        if "max_tokens" not in kwargs:
            kwargs["max_tokens"] = 8192
        
        result = await self.generate_text(prompt, system_prompt, **kwargs)
        text = result.get("text", "")
        
        # Clean up thinking tags
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        
        # Clean up markdown code blocks if present
        match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        else:
            first_brace = text.find("{")
            last_brace = text.rfind("}")
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                text = text[first_brace:last_brace + 1].strip()
            
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"error": "Failed to parse JSON", "raw_text": text}
    
    # Future methods to be implemented:
    # @abstractmethod
    # async def generate_image(self, prompt: str, **kwargs) -> Dict[str, Any]: pass
    #
    # @abstractmethod
    # async def generate_video(self, prompt: str, **kwargs) -> Dict[str, Any]: pass
