from typing import Dict, Type
from .interfaces import LLMProvider
from .bedrock_provider import BedrockProvider

class LLMFactory:
    """Simple factory for creating LLM providers"""
    
    _providers: Dict[str, Type[LLMProvider]] = {
        'bedrock': BedrockProvider
    }
    
    @classmethod
    def create_provider(cls, provider_name: str = 'bedrock') -> LLMProvider:
        """Create an LLM provider instance"""
        if provider_name not in cls._providers:
            available = ', '.join(cls._providers.keys())
            raise ValueError(f"Unknown provider '{provider_name}'. Available: {available}")
        
        provider_class = cls._providers[provider_name]
        return provider_class()
    
    @classmethod
    def register_provider(cls, name: str, provider_class: Type[LLMProvider]) -> None:
        """Register a new provider (for future use)"""
        cls._providers[name] = provider_class
    
    @classmethod
    def get_available_providers(cls) -> list[str]:
        """Get list of available provider names"""
        return list(cls._providers.keys())