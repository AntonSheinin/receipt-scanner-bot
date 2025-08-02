from typing import Dict, Type
from .interfaces import OCRProvider
from .textract_provider import TextractProvider
from .google_vision_provider import GoogleVisionProvider

class OCRFactory:
    """Simple factory for creating OCR providers"""
    
    _providers: Dict[str, Type[OCRProvider]] = {
        'aws_textract': TextractProvider,
        'google_vision': GoogleVisionProvider
    }
    
    @classmethod
    def create_provider(cls, provider_name: str, **kwargs) -> OCRProvider:
        """Create an OCR provider instance"""
        if provider_name not in cls._providers:
            available = ', '.join(cls._providers.keys())
            raise ValueError(f"Unknown OCR provider '{provider_name}'. Available: {available}")
        
        provider_class = cls._providers[provider_name]
        return provider_class(**kwargs)
