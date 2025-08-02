from typing import Dict, Optional
from enum import Enum
import logging

from config import PROCESSING_MODE, OCR_PROVIDER, LLM_PROVIDER
from utils.llm.factory import LLMFactory
from utils.ocr.factory import OCRFactory
from utils.ocr.interfaces import OCRResponse


logger = logging.getLogger(__name__)

class ProcessingMode(Enum):
    LLM_ONLY = "LLM_ONLY"
    OCR_THEN_LLM = "OCR_THEN_LLM"

class DocumentProcessorService:
    """Hybrid service for receipt processing using OCR and/or LLM"""
    
    def __init__(self):
        self.ocr = OCRFactory.create_provider(OCR_PROVIDER)
        self.llm = LLMFactory.create_provider(LLM_PROVIDER)
        self.processing_mode = PROCESSING_MODE
    
    def process_receipt(self, image_data: bytes) -> Dict:
        """Process receipt using specified mode"""
        
        logger.info(f"Processing receipt with mode: {self.processing_mode}")
        
        if self.processing_mode == ProcessingMode.LLM_ONLY.value:
            return self._process_with_llm_only(image_data)
        elif self.processing_mode == ProcessingMode.OCR_THEN_LLM.value:
            return self._process_with_ocr_then_llm(image_data)
        else:
            return self._process_with_llm_only(image_data)
    
    def _process_with_llm_only(self, image_data: bytes) -> Optional[Dict]:
        """Process using LLM only (existing method)"""
        try:
            result = self.llm.analyze_receipt(image_data)
            if result:
                result['processing_method'] = 'llm_only'
            return result
        except Exception as e:
            logger.error(f"LLM-only processing error: {e}")
            return None
    
    def _process_with_ocr_then_llm(self, image_data: bytes) -> Optional[Dict]:
        """Process using OCR for text extraction, then LLM for structuring"""
        try:
            # Step 1: Extract raw text with OCR
            ocr_result = self.ocr.extract_text(image_data)
            
            if not ocr_result.success or not ocr_result.raw_text.strip():
                logger.warning("OCR failed to extract text, falling back to LLM-only")
                return self._process_with_llm_only(image_data)
            
            # Step 2: Use LLM to structure the OCR text
            structured_result = self.llm.structure_ocr_text(ocr_result.raw_text)
            
            if structured_result:
                structured_result['processing_method'] = 'ocr_then_llm'
                structured_result['ocr_confidence'] = ocr_result.confidence
                return structured_result
            
            # Fallback to LLM-only if structuring fails
            logger.warning("LLM structuring failed, falling back to LLM-only")
            return self._process_with_llm_only(image_data)
            
        except Exception as e:
            logger.error(f"OCR+LLM processing error: {e}")
            return self._process_with_llm_only(image_data)