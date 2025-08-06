from typing import Dict, Optional
from enum import Enum
import logging

from config import OCR_PROCESSING_MODE, DOCUMENT_PROCESSING_MODE, OCR_PROVIDER, LLM_PROVIDER, setup_logging
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

class DocumentProcessorService:
    """Hybrid service for receipt processing using OCR and/or LLM"""

    def __init__(self):
        self.ocr = ProviderFactory.create_ocr_provider(OCR_PROVIDER)
        self.llm = LLMService(LLM_PROVIDER)
        self.image_preprocessor = ImagePreprocessorPillow()
        self.document_processing_mode = DOCUMENT_PROCESSING_MODE
        self.ocr_processing_mode = OCR_PROCESSING_MODE

    def process_receipt(self, image_data: bytes) -> Dict:
        """Process receipt using specified mode"""

        logger.info(f"Processing receipt with mode: {self.document_processing_mode}")

        if self.document_processing_mode == DocumentProcessingMode.LLM.value:
            return self._process_llm(image_data)

        elif self.document_processing_mode == DocumentProcessingMode.OCR_LLM.value:
            return self._process_ocr_llm(image_data)

        elif self.document_processing_mode == DocumentProcessingMode.PP_OCR_LLM.value:
            return self._process_pp_ocr_llm(image_data)

        else:
            return self._process_llm(image_data)

    def _process_llm(self, image_data: bytes) -> Optional[Dict]:
        """Process using LLM only (existing method)"""

        logger.info("Processing receipt with LLM only")

        try:
            result = self.llm.analyze_receipt(image_data)
            if result:
                result['processing_method'] = 'llm'
            return result
        except Exception as e:
            logger.error(f"LLM-only processing error: {e}")
            return None

    def _process_ocr_llm(self, image_data: bytes) -> Optional[Dict]:
        """Process using OCR for text extraction, then LLM for structuring"""

        logger.info("Processing receipt with OCR then LLM")

        try:

            # Step 1: Extract raw text with OCR
            ocr_result = self.ocr.extract_raw_text(image_data) if self.ocr_processing_mode == OCRProcessingMode.RAW_TEXT.value else self.ocr.extract_receipt_data(image_data)

            if not ocr_result.success or not ocr_result.raw_text.strip():
                logger.warning("OCR failed to extract text, falling back to LLM-only")
                return self._process_llm(image_data)

            # Step 2: Use LLM to structure the OCR text
            structured_result = self.llm.structure_ocr_text(ocr_result.raw_text)

            if structured_result:
                structured_result['processing_method'] = 'ocr_llm'
                structured_result['ocr_confidence'] = ocr_result.confidence
                return structured_result

            # Fallback to LLM-only if structuring fails
            logger.warning("LLM structuring failed, falling back to LLM-only")
            return self._process_llm(image_data)

        except Exception as e:
            logger.error(f"OCR+LLM processing error: {e}")
            return self._process_llm(image_data)

    def _process_pp_ocr_llm(self, image_data: bytes) -> Optional[Dict]:
        """Process using pre-processing OCR, then LLM for structuring"""

        logger.info("Processing receipt with pre-processing OCR then LLM")

        # Enhance image before OCR
        logger.info("Enhancing receipt image for better OCR accuracy")
        image_data = self.image_preprocessor.enhance_image(image_data)

        return self._process_ocr_llm(image_data)
