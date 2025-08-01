from typing import Dict, Optional
from enum import Enum
import logging

from services.llm_service import LLMService
from utils.ocr.factory import OCRFactory
from utils.ocr.interfaces import OCRResponse


logger = logging.getLogger(__name__)

class ProcessingMode(Enum):
    OCR_ONLY = "ocr_only"
    LLM_ONLY = "llm_only" 
    OCR_THEN_LLM = "ocr_then_llm"
    AUTO = "auto"

class DocumentProcessorService:
    """Hybrid service for receipt processing using OCR and/or LLM"""
    
    def __init__(self, ocr_provider: str = 'textract', llm_provider: str = 'bedrock'):
        self.ocr = OCRFactory.create_provider(ocr_provider)
        self.llm = LLMService(llm_provider)
    
    def process_receipt(self, image_data: bytes, mode: ProcessingMode = ProcessingMode.AUTO) -> Optional[Dict]:
        """Process receipt using specified mode"""
        
        if mode == ProcessingMode.AUTO:
            mode = self._determine_best_mode(image_data)
        
        logger.info(f"Processing receipt with mode: {mode.value}")
        
        if mode == ProcessingMode.OCR_ONLY:
            return self._process_with_ocr_only(image_data)
        elif mode == ProcessingMode.LLM_ONLY:
            return self._process_with_llm_only(image_data)
        elif mode == ProcessingMode.OCR_THEN_LLM:
            return self._process_with_ocr_then_llm(image_data)
        
        return None
    
    def _process_with_ocr_only(self, image_data: bytes) -> Optional[Dict]:
        """Process using OCR only"""
        try:
            ocr_result = self.ocr.extract_receipt_data(image_data)
            
            if not ocr_result.success:
                logger.warning(f"OCR failed: {ocr_result.error_message}")
                return None
            
            # Convert OCR result to standard format
            receipt_data = {
                'store_name': ocr_result.store_name or '',
                'date': ocr_result.date or '',
                'receipt_number': ocr_result.receipt_number,
                'payment_method': ocr_result.payment_method or 'other',
                'total': float(ocr_result.total) if ocr_result.total else 0,
                'items': [
                    {
                        'name': item.name,
                        'price': float(item.price),
                        'quantity': item.quantity,
                        'category': item.category or 'other'
                    }
                    for item in ocr_result.items
                ],
                'processing_method': 'ocr_only',
                'confidence': ocr_result.confidence
            }
            
            return receipt_data
            
        except Exception as e:
            logger.error(f"OCR-only processing error: {e}")
            return None
    
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
    
    def _determine_best_mode(self, image_data: bytes) -> ProcessingMode:
        """Automatically determine the best processing mode"""
        try:
            # Quick OCR test to assess image quality
            ocr_result = self.ocr.extract_text(image_data)
            
            if not ocr_result.success:
                return ProcessingMode.LLM_ONLY
            
            # If OCR confidence is high and text is substantial, use OCR+LLM
            if ocr_result.confidence > 80 and len(ocr_result.raw_text) > 100:
                return ProcessingMode.OCR_THEN_LLM
            
            # If OCR extracted some text but lower confidence, still try OCR+LLM
            if ocr_result.raw_text and len(ocr_result.raw_text) > 50:
                return ProcessingMode.OCR_THEN_LLM
            
            # Fall back to LLM for difficult images
            return ProcessingMode.LLM_ONLY
            
        except Exception as e:
            logger.warning(f"Auto-mode determination failed: {e}")
            return ProcessingMode.LLM_ONLY