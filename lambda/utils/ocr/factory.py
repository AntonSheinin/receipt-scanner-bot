from typing import Dict, Type
from .interfaces import OCRProvider
from .textract_provider import TextractProvider

class OCRFactory:
    """Simple factory for creating OCR providers"""
    
    _providers: Dict[str, Type[OCRProvider]] = {
        'textract': TextractProvider
    }
    
    @classmethod
    def create_provider(cls, provider_name: str = 'textract', **kwargs) -> OCRProvider:
        """Create an OCR provider instance"""
        if provider_name not in cls._providers:
            available = ', '.join(cls._providers.keys())
            raise ValueError(f"Unknown OCR provider '{provider_name}'. Available: {available}")
        
        provider_class = cls._providers[provider_name]
        return provider_class(**kwargs)
    
    @classmethod
    def get_available_providers(cls) -> list[str]:
        """Get list of available provider names"""
        return list(cls._providers.keys())