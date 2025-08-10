"""
Receipt Processing Service
"""
import logging
import uuid
from typing import Dict

from services.telegram_service import TelegramService
from services.storage_service import StorageService
from services.document_processor_service import DocumentProcessorService
from utils.helpers import create_response
from config import MAX_ITEMS_DISPLAY, MAX_ITEM_NAME_LENGTH, setup_logging


setup_logging()
logger = logging.getLogger(__name__)

class ReceiptService:
    """Service for receipt processing"""

    def __init__(self):
        self.telegram = TelegramService()
        self.storage = StorageService()
        self.processor = DocumentProcessorService()

    def process_receipt(self, message: Dict, chat_id: int) -> Dict:
        """Process receipt photo end-to-end"""

        self.telegram.send_typing(chat_id)

        # Download photo

        logger.info("Downloading receipt photo")

        photo_data = self.telegram.download_photo(message['photo'])
        if not photo_data:
            return self.telegram.send_error(chat_id, "Failed to download image. Please try again.")

        receipt_id = str(uuid.uuid4())
        user_id = str(chat_id)

        # Store image

        logger.info(f"Storing receipt image with ID: {receipt_id} for user: {user_id}")

        self.telegram.send_message(chat_id, "📁 Storing image...")
        image_url = self.storage.store_raw_image(receipt_id, photo_data)
        if not image_url:
            return self.telegram.send_error(chat_id, "Failed to store image. Please try again.")

        # Analyze receipt using hybrid processor

        logger.info(f"Analyzing receipt with ID: {receipt_id}")

        self.telegram.send_message(chat_id, "🔍 Analyzing receipt... Please wait.")
        receipt_data = self.processor.process_receipt(photo_data)

        if not receipt_data:
            return self.telegram.send_error(chat_id, "Could not process receipt. Please ensure the image is clear and contains a valid receipt.")

        try:
            # Store data and respond

            logger.info(f"Storing receipt data for ID: {receipt_id}")

            self.storage.store_receipt_data(receipt_id, user_id, receipt_data, image_url)
            response_text = self._format_receipt_response(receipt_data, receipt_id)
            self.telegram.send_message(chat_id, response_text)

            return create_response(200, {"status": "success"})

        except Exception as e:
            logger.error(f"Receipt processing error: {e}", exc_info=True)
            return self.telegram.send_error(chat_id, "An error occurred while processing your receipt.")

    def _format_receipt_response(self, receipt_data: Dict, receipt_id: str) -> str:
        """Format receipt data for Telegram with Hebrew support"""
        try:
            result = "✅ ניתוח הקבלה הושלם \n\n"

            # Store info - no encoding/decoding needed for Hebrew
            if receipt_data.get('store_name'):
                store_name = str(receipt_data['store_name'])
                result += f"🏪 חנות : {store_name}\n"

            if receipt_data.get('date'):
                result += f"📅 תאריך : {receipt_data['date']}\n"

            if receipt_data.get('receipt_number'):
                receipt_num = str(receipt_data['receipt_number'])
                result += f"🧾 מס׳ קבלה : {receipt_num}\n"

            if receipt_data.get('payment_method'):
                payment_icons = {
                    'cash': '💵',
                    'credit_card': '💳',
                    'other': '💰'
                }
                payment_labels = {
                    'cash': 'מזומן',
                    'credit_card': 'כרטיס אשראי',
                    'other': 'אחר'
                }
                method = receipt_data['payment_method']
                icon = payment_icons.get(method, '💰')
                label = payment_labels.get(method, method.replace('_', ' ').title())
                result += f"{icon} אמצעי תשלום : {label}\n"

            result += "\n"

            # Items section with proper price calculation
            items = receipt_data.get('items', [])
            if items:
                result += "📋 פריטים :\n"
                items_to_show = items[:MAX_ITEMS_DISPLAY]

                for item in items_to_show:
                    # Get item details
                    name = str(item.get('name', 'פריט לא ידוע'))

                    # Truncate long names
                    if len(name) > MAX_ITEM_NAME_LENGTH:
                        name = name[:MAX_ITEM_NAME_LENGTH-3] + "..."

                    # Get price and quantity
                    unit_price = float(item.get('price', 0))
                    quantity = float(item.get('quantity', 1))
                    discount = float(item.get('discount', 0))

                    # Calculate actual price: (unit_price * quantity) + discount
                    # Note: discount is negative, so adding it reduces the price
                    actual_price = (unit_price * quantity) + discount

                    # Format the line
                    line = f"• {name}"

                    # Show quantity if not 1 (handle both int and float quantities)
                    if quantity != 1:
                        if quantity == int(quantity):
                            line += f" (x{int(quantity)})"
                        else:
                            line += f" ({quantity:.3f})"

                    # Show unit price
                    line += f" - ₪{actual_price:.2f}"

                    # Add category if exists
                    category_labels = {
                            'food': 'מזון',
                            'beverages': 'משקאות',
                            'household': 'בית',
                            'electronics': 'אלקטרוניקה',
                            'clothing': 'ביגוד',
                            'pharmacy': 'בית מרקחת',
                            'deposit': 'פיקדון',
                            'other': 'אחר'
                        }

                    category = item.get('category', '')

                    result += line + " [" + category_labels.get(category, '') + "] \n"

                # Show if more items exist
                if len(items) > MAX_ITEMS_DISPLAY:
                    result += f"... ועוד {len(items) - MAX_ITEMS_DISPLAY} פריטים \n"

            # Total section
            if receipt_data.get('total'):
                total = float(receipt_data.get('total', 0))
                result += f"\n💰 סה״כ : ₪{total:.2f}"

            result += f"\n✅ נשמר בהצלחה במסד הנתונים "

            # Processing method indicator (if available)
            if receipt_data.get('processing_method'):
                methods = {
                    'llm': 'AI Vision',
                    'ocr_llm': 'OCR + AI',
                    'pp_ocr_llm': 'Enhanced OCR + AI'
                }
                result += f"\n\n{methods.get(receipt_data['processing_method'], '🔍')}"

            return result

        except Exception as e:
            logger.error(f"Formatting error: {e}")
            return f"✅ הקבלה עובדה בהצלחה! \n\n🆔 *מזהה | ID: `{receipt_id}`\n✅ נשמר במסד הנתונים"
