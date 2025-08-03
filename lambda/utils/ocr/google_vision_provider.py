from google.cloud import vision
from typing import List, Dict, Any
from decimal import Decimal
from .interfaces import LineItem, OCRProvider, OCRResponse
import json
import os
import re   
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
        return self.extract_receipt_data(image_data)
    
    def extract_receipt_data(self, image_data: bytes) -> OCRResponse:
        """Extract structured receipt data using document text detection"""
        try:
            image = vision.Image(content=image_data)
            
            # Use document_text_detection for structured layout
            response = self.client.document_text_detection(image=image)
            
            if response.error.message:
                raise Exception(response.error.message)
            
            # Extract structured data from document
            structured_data = self._extract_structured_data(response)
            
            # Get raw text for fallback
            raw_text = response.full_text_annotation.text if response.full_text_annotation else ""
            
            return OCRResponse(
                raw_text=raw_text,
                store_name=structured_data.get('store_name'),
                date=structured_data.get('date'),
                receipt_number=structured_data.get('receipt_number'),
                total=structured_data.get('total'),
                payment_method=structured_data.get('payment_method') or self._detect_payment_method(raw_text),
                items=structured_data.get('items', []),
                confidence=self._calculate_document_confidence(response)
            )
            
        except Exception as e:
            logger.error(f"Google Vision structured extraction error: {e}")
            # Fallback to basic text extraction
            return self.extract_text(image_data)

    def _extract_structured_data(self, response) -> Dict[str, Any]:
        """Extract structured receipt data from Google Vision document response"""
        if not response.full_text_annotation:
            return {}
        
        structured_data = {}
        blocks = []
        
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
        structured_data.update(self._analyze_receipt_blocks(blocks))
        
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
                    result['date'] = self._normalize_date(date_match.group())
            
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
                        items.append(LineItem(
                            name=item_name,
                            price=price,
                            quantity=1,
                            category=self._categorize_item(item_name)
                        ))
                except:
                    pass
        
        result['items'] = items
        return result 

    def _categorize_item(self, item_name: str) -> str:
        """Categorize item based on name"""
        name_lower = item_name.lower()
        
        food_keywords = ['bread', 'milk', 'cheese', 'meat', 'fruit', 'vegetable']
        beverage_keywords = ['juice', 'water', 'soda', 'coffee', 'tea']
        household_keywords = ['soap', 'detergent', 'paper', 'towel', 'cas', 'gasoline']
    
        if any(keyword in name_lower for keyword in food_keywords):
            return 'food'
        elif any(keyword in name_lower for keyword in beverage_keywords):
            return 'beverages'
        elif any(keyword in name_lower for keyword in household_keywords):
            return 'household'
        
        return 'other'

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
        
        # Cash indicators
        cash_indicators = ['מזומן', 'מזומנים', 'cash']
        
        # Card indicators
        card_indicators = ['אשראי', 'כרטיס', 'ויזה', 'מאסטרקארד', 'card', 'credit', 'visa', 'mastercard', 'debit']
        
        if any(indicator in text_lower for indicator in cash_indicators):
            return 'cash'
        
        if any(indicator in text_lower for indicator in card_indicators):
            return 'credit_card'
        
        return 'other'