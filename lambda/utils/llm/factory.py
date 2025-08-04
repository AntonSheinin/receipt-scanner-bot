from typing import Dict, Type
from utils.llm.interfaces import LLMProvider
from utils.llm.bedrock_provider import BedrockProvider

class LLMFactory:
    """Simple factory for creating LLM providers"""
    
    _providers: Dict[str, Type[LLMProvider]] = {
        'bedrock': BedrockProvider
    }
    
    @classmethod
    def create_provider(cls, provider_name: str) -> LLMProvider:
        """Create an LLM provider instance"""
        if provider_name not in cls._providers:
            available = ', '.join(cls._providers.keys())
            raise ValueError(f"Unknown provider '{provider_name}'. Available: {available}")
        
        provider_class = cls._providers[provider_name]
        return provider_class()
    