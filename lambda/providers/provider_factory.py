"""
    Provider Factory for creating various service providers
"""

from typing import Dict, Type
from providers.provider_interfaces import LLMProvider, OCRProvider, ImageStorage, DocumentStorage
from providers.llm.bedrock_provider import BedrockProvider
from providers.llm.openai_provider import OpenAIProvider
from providers.ocr.aws_textract_provider import TextractProvider
from providers.ocr.google_vision_provider import GoogleVisionProvider
from providers.storage.s3_storage_provider import S3StorageProvider
from providers.storage.postgresql_storage_provider import PostgreSQLStorageProvider


class ProviderFactory:
    """Unified factory for creating all providers"""

    _llm_providers: Dict[str, Type[LLMProvider]] = {
        'bedrock': BedrockProvider,
        'openai': OpenAIProvider
    }

    _ocr_providers: Dict[str, Type[OCRProvider]] = {
        'aws_textract': TextractProvider,
        'google_vision': GoogleVisionProvider
    }

    _image_storage_providers: Dict[str, Type[ImageStorage]] = {
        's3': S3StorageProvider
    }

    _document_storage_providers: Dict[str, Type[DocumentStorage]] = {
        'postgresql': PostgreSQLStorageProvider
    }

    @classmethod
    def create_llm_provider(cls, provider_name: str) -> LLMProvider:
        if provider_name not in cls._llm_providers:
            available = ', '.join(cls._llm_providers.keys())
            raise ValueError(f"Unknown LLM provider '{provider_name}'. Available: {available}")

        provider_class = cls._llm_providers[provider_name]
        return provider_class()

    @classmethod
    def create_ocr_provider(cls, provider_name: str) -> OCRProvider:
        if provider_name not in cls._ocr_providers:
            available = ', '.join(cls._ocr_providers.keys())
            raise ValueError(f"Unknown OCR provider '{provider_name}'. Available: {available}")

        provider_class = cls._ocr_providers[provider_name]
        return provider_class()

    @classmethod
    def create_image_storage(cls, provider_name: str) -> ImageStorage:
        if provider_name not in cls._image_storage_providers:
            available = ', '.join(cls._image_storage_providers.keys())
            raise ValueError(f"Unknown image storage provider '{provider_name}'. Available: {available}")

        provider_class = cls._image_storage_providers[provider_name]
        return provider_class()

    @classmethod
    def create_document_storage(cls, provider_name: str) -> DocumentStorage:
        if provider_name not in cls._document_storage_providers:
            available = ', '.join(cls._document_storage_providers.keys())
            raise ValueError(f"Unknown document storage provider '{provider_name}'. Available: {available}")

        provider_class = cls._document_storage_providers[provider_name]
        return provider_class()
