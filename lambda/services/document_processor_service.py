from abc import ABC, abstractmethod
from typing import Dict, Optional
from enum import Enum
import logging

from config import OCR_PROCESSING_MODE, DOCUMENT_PROCESSING_MODE, OCR_PROVIDER, LLM_PROVIDER, setup_logging
from services.storage_service import StorageService
from services.llm_service import LLMService
from provider_factory import ProviderFactory
from utils.image_preprocessor.pillow_preprocessor import ImagePreprocessorPillow

setup_logging()
logger = logging.getLogger(__name__)

class OCRProcessingMode(Enum):
    RAW_TEXT = "raw_text"
    STRUCTURED_TEXT = "structured_text"

class DocumentProcessingMode(Enum):
    LLM = "llm"
    OCR_LLM = "ocr_llm"
    PP_OCR_LLM = "pp_ocr_llm"

# --- Strategy Interface ---
class ReceiptProcessingStrategy(ABC):
    @abstractmethod
    def process(self, image_data: bytes) -> Optional[Dict]:
        pass

# --- Concrete Strategies ---
class LLMProcessingStrategy(ReceiptProcessingStrategy):
    def __init__(self, llm: LLMService):
        self.llm = llm

    def process(self, image_data: bytes) -> Optional[Dict]:
        """
        Process receipt image using LLM only.
        """
        logger.info("Processing receipt with LLM only")

        try:
            result = self.llm.analyze_receipt(image_data)
            if result:
                result['processing_method'] = 'llm'
            return result

        except Exception as e:
            logger.error(f"LLM-only processing error: {e}")
            return None

class OCRLLMProcessingStrategy(ReceiptProcessingStrategy):
    def __init__(self, ocr, llm: LLMService, ocr_processing_mode):
        self.ocr = ocr
        self.llm = llm
        self.ocr_processing_mode = ocr_processing_mode

    def process(self, image_data: bytes) -> Optional[Dict]:
        """
        Process receipt image using OCR then LLM.
        """
        logger.info("Processing receipt with OCR then LLM")

        try:
            ocr_result = self.ocr.extract_raw_text(image_data) if self.ocr_processing_mode == OCRProcessingMode.RAW_TEXT.value else self.ocr.extract_receipt_data(image_data)

            if not ocr_result.success or not ocr_result.raw_text.strip():
                logger.warning("OCR failed to extract text, falling back to LLM-only")
                return LLMProcessingStrategy(self.llm).process(image_data)

            structured_result = self.llm.structure_ocr_text(ocr_result.raw_text)

            if structured_result:
                structured_result['processing_method'] = 'ocr_llm'
                structured_result['ocr_confidence'] = ocr_result.confidence
                return structured_result

            logger.warning("LLM structuring failed, falling back to LLM-only")
            return LLMProcessingStrategy(self.llm).process(image_data)

        except Exception as e:
            logger.error(f"OCR+LLM processing error: {e}")
            return LLMProcessingStrategy(self.llm).process(image_data)

class PPOCRLLMProcessingStrategy(ReceiptProcessingStrategy):
    def __init__(self, image_preprocessor, ocr, llm: LLMService, ocr_processing_mode):
        self.image_preprocessor = image_preprocessor
        self.ocr_llm_strategy = OCRLLMProcessingStrategy(ocr, llm, ocr_processing_mode)

    def process(self, image_data: bytes) -> Optional[Dict]:
        logger.info("Processing receipt with pre-processing OCR then LLM")

        logger.info("Enhancing receipt image for better OCR accuracy")
        image_data = self.image_preprocessor.enhance_image(image_data)

        storage = StorageService()
        storage.store_raw_image("test", image_data)

        return self.ocr_llm_strategy.process(image_data)

# --- Context ---
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

    def process_receipt(self, image_data: bytes) -> Dict:
        """Process receipt using specified mode"""

        logger.info(f"Processing receipt with mode: {self.document_processing_mode}")

        strategy = self.strategies.get(self.document_processing_mode, self.strategies[DocumentProcessingMode.LLM.value])

        return strategy.process(image_data)
