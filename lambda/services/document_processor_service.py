"""
    Document Processor Service module
"""

from abc import ABC, abstractmethod
from typing import Optional
from enum import Enum
import logging
from config import OCR_PROCESSING_MODE, DOCUMENT_PROCESSING_MODE, OCR_PROVIDER, LLM_PROVIDER, setup_logging
from services.llm_service import LLMService
from providers.provider_factory import ProviderFactory
from providers.image_preprocessor.pillow_preprocessor import ImagePreprocessorPillow
from schemas import ReceiptAnalysisResult


setup_logging()
logger = logging.getLogger(__name__)

class OCRProcessingMode(Enum):
    RAW_TEXT = "raw_text"
    STRUCTURED_TEXT = "structured_text"

class DocumentProcessingMode(Enum):
    LLM = "llm"
    OCR_LLM = "ocr_llm"
    PP_OCR_LLM = "pp_ocr_llm"

class ReceiptProcessingStrategy(ABC):
    @abstractmethod
    def process(self, image_data: bytes) -> Optional[ReceiptAnalysisResult]:
        pass

class LLMProcessingStrategy(ReceiptProcessingStrategy):
    def __init__(self, llm: LLMService):
        self.llm = llm

    def process(self, image_data: bytes) -> Optional[ReceiptAnalysisResult]:
        """
        Process receipt image using LLM only.
        """
        logger.info("Processing receipt with LLM only")

        try:
            return self.llm.analyze_receipt(image_data)

        except Exception as e:
            logger.error(f"LLM-only processing error: {e}")
            return None

class OCRLLMProcessingStrategy(ReceiptProcessingStrategy):
    def __init__(self, ocr, llm: LLMService, ocr_processing_mode):
        self.ocr = ocr
        self.llm = llm
        self.ocr_processing_mode = ocr_processing_mode

    def process(self, image_data: bytes) -> Optional[ReceiptAnalysisResult]:
        """
        Process receipt image using OCR then LLM.
        """
        logger.info("Processing receipt with OCR then LLM")

        try:
            ocr_result = self.ocr.extract_raw_text(image_data) if self.ocr_processing_mode == OCRProcessingMode.RAW_TEXT.value else self.ocr.extract_receipt_data(image_data)

            if not ocr_result.success or not ocr_result.raw_text.strip():
                logger.error("OCR failed to extract text")
                return None

            structured_result = self.llm.structure_ocr_text(ocr_result.raw_text)

            if not structured_result:
                logger.error("LLM structuring failed")
                return None

            return structured_result

        except Exception as e:
            logger.error(f"OCR+LLM processing error: {e}")
            return None


class PPOCRLLMProcessingStrategy(ReceiptProcessingStrategy):
    def __init__(self, image_preprocessor, ocr, llm: LLMService, ocr_processing_mode):
        self.image_preprocessor = image_preprocessor
        self.ocr_llm_strategy = OCRLLMProcessingStrategy(ocr, llm, ocr_processing_mode)

    def process(self, image_data: bytes) -> Optional[ReceiptAnalysisResult]:
        logger.info("Processing receipt with pre-processing OCR then LLM")

        logger.info("Enhancing receipt image for better OCR accuracy")
        enhanced_image = self.image_preprocessor.enhance_image(image_data)

        result = self.ocr_llm_strategy.process(enhanced_image)

        return result

class DocumentProcessorService:
    """Hybrid service for receipt processing using OCR and/or LLM"""

    def __init__(self):
        self.ocr = ProviderFactory.create_ocr_provider(OCR_PROVIDER)
        self.llm = LLMService(LLM_PROVIDER)
        self.image_preprocessor = ImagePreprocessorPillow()
        self.document_processing_mode = DOCUMENT_PROCESSING_MODE
        self.ocr_processing_mode = OCR_PROCESSING_MODE

        # Strategy selection
        self.strategies = {
            DocumentProcessingMode.LLM.value: LLMProcessingStrategy(self.llm),
            DocumentProcessingMode.OCR_LLM.value: OCRLLMProcessingStrategy(self.ocr, self.llm, self.ocr_processing_mode),
            DocumentProcessingMode.PP_OCR_LLM.value: PPOCRLLMProcessingStrategy(self.image_preprocessor, self.ocr, self.llm, self.ocr_processing_mode),
        }

    def process_receipt(self, image_data: bytes) -> Optional[ReceiptAnalysisResult]:
        """Process receipt using specified mode"""

        logger.info(f"Processing receipt with mode: {self.document_processing_mode}")

        strategy = self.strategies.get(self.document_processing_mode, self.strategies[DocumentProcessingMode.LLM.value])

        logger.info(f"Using strategy: {strategy.__class__.__name__}")

        return strategy.process(image_data)
