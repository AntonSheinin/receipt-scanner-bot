from google.cloud import vision
import base64
from typing import Optional, List, Dict, Any
from .interfaces import OCRProvider, OCRResponse, LineItem
import json
import os   
import logging
from google.oauth2 import service_account


logger = logging.getLogger(__name__)

class GoogleVisionProvider(OCRProvider):
    def __init__(self):
        # Initialize client with service account key
        credentials_json = os.getenv('GOOGLE_CREDENTIALS_JSON')

        if credentials_json:
            creds = service_account.Credentials.from_service_account_info(
                json.loads(credentials_json)
            )
            self.client = vision.ImageAnnotatorClient(credentials=creds)
        else:
            logger.error("GOOGLE_CREDENTIALS_JSON environment variable not set")
            self.client = vision.ImageAnnotatorClient()
    
    def extract_text(self, image_data: bytes) -> OCRResponse:
        """Extract raw text using Google Vision"""
        try:
            image = vision.Image(content=image_data)
            response = self.client.text_detection(image=image)
            
            if response.error.message:
                raise Exception(response.error.message)
            
            texts = response.text_annotations
            raw_text = texts[0].description if texts else ""

            logger.info(f"Google Vision raw text extracted: {raw_text[:100]}...")
            logger.info(f"Extracted text: {raw_text[:100]}...") 
            logger.info(f"Total text annotations: {texts}")
            logger.info(f"Text confidence: {texts[0].confidence if texts else 'N/A'}")

            return OCRResponse(
                raw_text=raw_text,
                confidence=self._calculate_confidence(texts),
                payment_method=self._detect_payment_method(raw_text)
            )
            
        except Exception as e:
            logger.error(f"Google Vision text extraction error: {e}")
            return OCRResponse(
                raw_text="",
                success=False,
                error_message=str(e)
            )
    
    def extract_receipt_data(self, image_data: bytes) -> OCRResponse:
        """Extract structured data - fallback to text extraction"""
        return self.extract_text(image_data)
    
    def _detect_payment_method(self, text: str) -> str:
        """Detect payment method from text"""
        if not text:
            return 'other'
        
        text_lower = text.lower()
        
        # Cash indicators
        cash_indicators = ['מזומן', 'מזומנים', 'cash']
        
        # Card indicators
        card_indicators = ['אשראי', 'כרטיס', 'ויזה', 'מאסטרקארד', 'card', 'credit', 'visa', 'mastercard', 'debit']
        
        if any(indicator in text_lower for indicator in cash_indicators):
            return 'cash'
        
        if any(indicator in text_lower for indicator in card_indicators):
            return 'credit_card'
        
        return 'other'
    
    def _calculate_confidence(self, text_annotations: List) -> float:
        """Calculate average confidence from Google Vision text annotations"""
        if not text_annotations or len(text_annotations) < 2:
            return 0.0
        
        # Skip the first annotation (it's the full text), use individual word confidences
        confidences = []
        for annotation in text_annotations[1:]:  # Skip first element
            if hasattr(annotation, 'confidence') and annotation.confidence:
                confidences.append(annotation.confidence * 100)  # Convert to percentage
        
        return sum(confidences) / len(confidences) if confidences else 85.0  # Default confidence