"""
    AWS Textract Provider module
"""

import boto3
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional, List, Dict, Any
from utils.helpers import normalize_date
from botocore.exceptions import ClientError
from config import setup_logging, AWS_REGION
from utils.category_manager import category_manager
from provider_interfaces import OCRProvider, OCRResponse
from receipt_schemas import ReceiptItem


setup_logging()
logger = logging.getLogger(__name__)

class TextractProvider(OCRProvider):
    """AWS Textract OCR provider"""

    def __init__(self):
        self.client = boto3.client('textract', region_name=AWS_REGION)

    def extract_raw_text(self, image_data: bytes) -> OCRResponse:
        """Extract raw text using DetectDocumentText"""

        logger.info("Extracting raw text using AWS Textract")

        try:
            response = self.client.detect_document_text(
                Document={'Bytes': image_data}
            )

            # Extract text lines
            text_lines = []
            confidences = []

            for block in response.get('Blocks', []):
                if block['BlockType'] == 'LINE':
                    text_lines.append(block['Text'])
                    confidences.append(block.get('Confidence', 0))

            raw_text = '\n'.join(text_lines)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0

            logger.info(f"Extracted raw text: {raw_text}")  # Log first 100 chars
            logger.info(f"Average confidence: {avg_confidence}")

            return OCRResponse(
                raw_text=raw_text,
                confidence=avg_confidence,
                payment_method=self._detect_payment_method(raw_text)
            )

        except ClientError as e:
            logger.error(f"Textract text extraction error: {e}")
            return OCRResponse(
                raw_text="",
                success=False,
                error_message=str(e)
            )

    def extract_receipt_data(self, image_data: bytes) -> OCRResponse:
        """Extract structured receipt data using AnalyzeExpense"""

        logger.info("Extracting structured receipt data using AWS Textract")

        try:
            response = self.client.analyze_expense(
                Document={'Bytes': image_data}
            )

            logger.info(f"Textract response: {response}")

            expense_docs = response.get('ExpenseDocuments', [])
            if not expense_docs:
                return self.extract_raw_text(image_data)  # Fallback

            expense_doc = expense_docs[0]

            # Extract summary fields
            summary = self._extract_summary_fields(expense_doc)

            # Extract line items
            items = self._extract_line_items(expense_doc)

            # Get raw text for payment method detection
            raw_text = self._extract_raw_text_from_blocks(expense_doc)

            logger.info(f"Extracted {len(items)} items from receipt")
            logger.info(f"Extracted items: {items}")
            logger.info(f"Extracted raw text: {raw_text[:100]}...")

            return OCRResponse(
                raw_text=raw_text,
                store_name=summary.get('store_name'),
                date=summary.get('date'),
                receipt_number=summary.get('receipt_number'),
                total=summary.get('total'),
                payment_method=summary.get('payment_method') or self._detect_payment_method(raw_text),
                items=items,
                confidence=self._calculate_avg_confidence(expense_doc)
            )

        except ClientError as e:
            logger.error(f"Textract expense analysis error: {e}")
            # Fallback to text extraction
            return self.extract_raw_text(image_data)

    def _extract_summary_fields(self, expense_doc: Dict[str, Any]) -> Dict[str, Any]:
        """Extract summary fields from expense document"""
        summary = {}

        for field in expense_doc.get('SummaryFields', []):
            field_type = field.get('Type', {}).get('Text', '').lower()
            value = field.get('ValueDetection', {}).get('Text', '')
            confidence = field.get('ValueDetection', {}).get('Confidence', 0)

            if confidence < 70:  # Skip low confidence fields
                continue

            if field_type in ['vendor_name', 'merchant_name']:
                summary['store_name'] = value
            elif field_type == 'invoice_receipt_date':
                summary['date'] = normalize_date(value)
            elif field_type == 'total':
                summary['total'] = self._parse_amount(value)
            elif field_type in ['invoice_receipt_id', 'receipt_id']:
                summary['receipt_number'] = value

        return summary

    # TODO : Implement converting extracted LineItem into ReceiptItem
    def _extract_line_items(self, expense_doc: Dict[str, Any]) -> List[ReceiptItem]:
        """Extract line items from expense document"""
        items = []

        for group in expense_doc.get('LineItemGroups', []):
            for line_item in group.get('LineItems', []):
                item_data = {}

                for field in line_item.get('LineItemExpenseFields', []):
                    field_type = field.get('Type', {}).get('Text', '').lower()
                    value = field.get('ValueDetection', {}).get('Text', '')

                    if field_type == 'item':
                        item_data['name'] = value
                    elif field_type == 'price':
                        item_data['price'] = self._parse_amount(value)
                    elif field_type == 'quantity':
                        item_data['quantity'] = self._parse_quantity(value)

                if item_data.get('name'):
                    subcategory = self._categorize_item_to_subcategory(item_data['name'])
                    category = category_manager.get_category_from_subcategory(subcategory)

                    try:
                        receipt_item = ReceiptItem(
                            name=item_data['name'],
                            price=Decimal(item_data.get('price', 0)),
                            quantity=Decimal(item_data.get('quantity', 1)),
                            category=category,
                            subcategory=subcategory,
                            discount=Decimal(0)
                        )
                        items.append(receipt_item)
                    except Exception as e:
                        logger.warning(f"Failed to create ReceiptItem: {e}")
                        continue

        return items

    def _parse_amount(self, amount_str: str) -> Optional[Decimal]:
        """Parse amount string to Decimal"""
        if not amount_str:
            return None

        try:
            # Remove currency symbols and spaces
            cleaned = ''.join(c for c in amount_str if c.isdigit() or c in '.,')

            if not cleaned:
                return None

            # Handle decimal separators
            if ',' in cleaned and '.' in cleaned:
                cleaned = cleaned.replace(',', '')
            elif ',' in cleaned and cleaned.count(',') == 1:
                parts = cleaned.split(',')
                if len(parts[1]) == 2:  # Decimal separator
                    cleaned = cleaned.replace(',', '.')

            return Decimal(cleaned)

        except (ValueError, InvalidOperation):
            logger.warning(f"Could not parse amount: {amount_str}")
            return None

    def _parse_quantity(self, qty_str: str) -> int:
        """Parse quantity string to int"""
        try:
            digits = ''.join(c for c in qty_str if c.isdigit())
            return int(digits) if digits else 1
        except ValueError:
            return 1

    def _detect_payment_method(self, text: str) -> str:
        """Detect payment method from text"""
        text_lower = text.lower()

        if any(indicator in text_lower for indicator in ['cash', 'מזומן']):
            return 'cash'
        elif any(indicator in text_lower for indicator in ['card', 'credit', 'visa', 'mastercard', 'אשראי']):
            return 'credit_card'

        return 'other'

    def _calculate_avg_confidence(self, expense_doc: Dict[str, Any]) -> float:
        """Calculate average confidence score"""
        confidences = []

        for field in expense_doc.get('SummaryFields', []):
            confidence = field.get('ValueDetection', {}).get('Confidence')
            if confidence:
                confidences.append(confidence)

        return sum(confidences) / len(confidences) if confidences else 0.0

    def _extract_raw_text_from_blocks(self, expense_doc: Dict[str, Any]) -> str:
        """Extract raw text from Textract expense document blocks"""
        try:
            text_lines = []

            # Extract text from summary fields
            for field in expense_doc.get('SummaryFields', []):
                field_text = field.get('Type', {}).get('Text', '')
                value_text = field.get('ValueDetection', {}).get('Text', '')
                if field_text:
                    text_lines.append(field_text)
                if value_text:
                    text_lines.append(value_text)

            # Extract text from line items
            for group in expense_doc.get('LineItemGroups', []):
                for line_item in group.get('LineItems', []):
                    for field in line_item.get('LineItemExpenseFields', []):
                        field_text = field.get('Type', {}).get('Text', '')
                        value_text = field.get('ValueDetection', {}).get('Text', '')
                        if field_text:
                            text_lines.append(field_text)
                        if value_text:
                            text_lines.append(value_text)

            return '\n'.join(text_lines)

        except Exception as e:
            logger.error(f"Error extracting raw text from blocks: {e}")
            return ""

    # TODO : implement
    def _categorize_item_to_subcategory(self, item_name: str) -> str:
        return ""
