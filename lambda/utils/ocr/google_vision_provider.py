"""
    Google Vision Provider module
"""

import json
import os
import re
import logging
from google.cloud import vision
from typing import List, Dict, Any
from decimal import Decimal
from config import setup_logging, GOOGLE_CREDENTIALS_JSON
from utils.helpers import normalize_date
from provider_interfaces import OCRProvider, OCRResponse
from receipt_schemas import ReceiptItem
from utils.category_manager import category_manager
from google.oauth2 import service_account


setup_logging()
logger = logging.getLogger(__name__)

class GoogleVisionProvider(OCRProvider):
    def __init__(self):
        # Initialize client with service account key

        if GOOGLE_CREDENTIALS_JSON:
            creds = service_account.Credentials.from_service_account_info(
                json.loads(GOOGLE_CREDENTIALS_JSON)
            )
            self.client = vision.ImageAnnotatorClient(credentials=creds)
        else:
            logger.error("GOOGLE_CREDENTIALS_JSON variable not set")
            self.client = vision.ImageAnnotatorClient()

    def extract_raw_text(self, image_data: bytes) -> OCRResponse:
        """Extract raw text using Google Vision"""

        logger.info("Extracting raw text using Google Vision")

        try:
            # Use text detection for raw text extraction
            response = self.client.text_detection(
                image=vision.Image(content=image_data),
                image_context=vision.ImageContext(language_hints=['he'])
            )

            if response.error.message:
                raise Exception(response.error.message)

            texts = response.text_annotations
            raw_text = texts[0].description if texts else ""

            logger.info(f"Google Vision raw text extracted: {raw_text}")

            return OCRResponse(
                raw_text=raw_text,
                confidence=0.0,  # text_detection() does not provide confidence for raw text
            )

        except Exception as e:
            logger.error(f"Google Vision text extraction error: {e}")
            return OCRResponse(
                raw_text="",
                success=False,
                error_message=str(e)
            )

    def extract_receipt_data(self, image_data: bytes) -> OCRResponse:
        """Extract structured receipt data using document text detection"""

        logger.info("Extracting structured receipt data using Google Vision")

        try:
            # Use document text detection for structured data
            response = self.client.document_text_detection(
                image=vision.Image(content=image_data),
                image_context=vision.ImageContext(language_hints=['he'])
            )

            if response.error.message:
                raise Exception(response.error.message)

            # Extract structured data from document
            structured_data = self._extract_structured_data(response)

            # Get raw text for fallback
            raw_text = response.full_text_annotation.text if response.full_text_annotation else ""
            confidence = self._calculate_document_confidence(response)

            logger.info(f"Google Vision structured data extracted: {structured_data}")
            logger.info(f"Google Vision raw text: {raw_text[:100]}...")
            logger.info(f"Google Vision confidence: {confidence}")

            return OCRResponse(
                raw_text=raw_text,
                store_name=structured_data.get('store_name'),
                date=structured_data.get('date'),
                receipt_number=structured_data.get('receipt_number'),
                total=structured_data.get('total'),
                payment_method=structured_data.get('payment_method') or self._detect_payment_method(raw_text),
                items=structured_data.get('items', []),
                confidence=confidence,
            )

        except Exception as e:
            logger.error(f"Google Vision structured extraction error: {e}")
            # Fallback to basic text extraction
            return self.extract_raw_text(image_data)

    def _extract_structured_data(self, response, analyze_blocks: bool = False) -> Dict[str, Any]:
        """Extract structured receipt data from Google Vision document response"""
        if not response.full_text_annotation:
            return {}

        structured_data = {}
        blocks: list[dict] = []

        # Extract text blocks with positions
        for page in response.full_text_annotation.pages:
            for block in page.blocks:
                block_text = ""
                block_words = []

                for paragraph in block.paragraphs:
                    for word in paragraph.words:
                        word_text = ''.join([symbol.text for symbol in word.symbols])
                        block_words.append(word_text)

                block_text = ' '.join(block_words)
                if block_text.strip():
                    blocks.append({
                        'text': block_text.strip(),
                        'confidence': block.confidence if hasattr(block, 'confidence') else None,
                        'bounds': self._extract_bounds(block.bounding_box) if block.bounding_box else None
                    })

        # Analyze blocks to extract receipt fields
        if analyze_blocks:
            structured_data.update(self._analyze_receipt_blocks(blocks))
        else:
            structured_data['items'] = blocks

        return structured_data

    def _analyze_receipt_blocks(self, blocks: List[Dict]) -> Dict[str, Any]:
        """Analyze text blocks to extract receipt information"""
        result = {}
        items = []

        for block in blocks:
            text = block['text']
            text_lower = text.lower()

            # Store name detection (usually at the top)
            if not result.get('store_name') and len(text) > 3 and not any(char.isdigit() for char in text):
                if any(indicator in text_lower for indicator in ['market', 'store', 'shop', 'ltd', 'inc']):
                    result['store_name'] = text

            # Date detection
            if not result.get('date'):
                date_match = re.search(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', text)
                if date_match:
                    result['date'] = normalize_date(date_match.group())

            # Receipt number detection
            if not result.get('receipt_number'):
                receipt_match = re.search(r'(?:receipt|trans|ref|#)\s*:?\s*(\w+)', text_lower)
                if receipt_match:
                    result['receipt_number'] = receipt_match.group(1)

            # Total amount detection
            if not result.get('total'):
                total_match = re.search(r'(?:total|sum)\s*:?\s*(\d+\.?\d*)', text_lower)
                if total_match:
                    try:
                        result['total'] = Decimal(total_match.group(1))
                    except:
                        pass

            # Item detection (text with price pattern)
            item_match = re.search(r'^(.+?)\s+(\d+\.?\d*)\s*$', text.strip())
            if item_match:
                item_name = item_match.group(1).strip()
                try:
                    price = Decimal(item_match.group(2))
                    if len(item_name) > 2 and price > 0:
                        item_dict = {
                            'name': item_name,
                            'price': float(price),  # Convert to float for JSON serialization
                            'quantity': 1.0,
                            'discount': 0.0
                        }
                        items.append(item_dict)

                except Exception as e:
                    logger.warning(f"Failed to create item dict for '{item_name}': {e}")
                    pass

        result['items'] = items
        return result

    def _extract_bounds(self, bounding_box) -> Dict[str, int]:
        """Extract bounding box coordinates"""
        if not bounding_box or not bounding_box.vertices:
            return {}

        vertices = bounding_box.vertices
        return {
            'left': min(v.x for v in vertices),
            'top': min(v.y for v in vertices),
            'right': max(v.x for v in vertices),
            'bottom': max(v.y for v in vertices)
        }

    def _calculate_document_confidence(self, response) -> float:
        """Calculate confidence from document response"""
        if not response.full_text_annotation:
            return 0.0

        confidences = []
        for page in response.full_text_annotation.pages:
            for block in page.blocks:
                if hasattr(block, 'confidence') and block.confidence:
                    confidences.append(block.confidence * 100)

        return sum(confidences) / len(confidences) if confidences else 85.0

    def _detect_payment_method(self, text: str) -> str:
        """Detect payment method from text"""
        if not text:
            return 'other'

        text_lower = text.lower()

        cash_indicators = ['מזומן', 'מזומנים', 'cash']
        card_indicators = ['אשראי', 'כרטיס', 'ויזה', 'מאסטרקארד', 'card', 'credit', 'visa', 'mastercard', 'debit']

        if any(indicator in text_lower for indicator in cash_indicators):
            return 'cash'

        if any(indicator in text_lower for indicator in card_indicators):
            return 'credit_card'

        return 'other'
