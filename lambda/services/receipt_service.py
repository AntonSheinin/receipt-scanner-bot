"""
    Receipt Processing Service module
"""

import logging
import uuid
from typing import Dict
from services.telegram_service import TelegramService
from services.storage_service import StorageService
from services.document_processor_service import DocumentProcessorService
from providers.helpers import create_response
from config import MAX_ITEMS_DISPLAY, MAX_ITEM_NAME_LENGTH, setup_logging
from providers.helpers import get_secure_user_id
from schemas import ReceiptAnalysisResult
from providers.category_manager import category_manager


setup_logging()
logger = logging.getLogger(__name__)

class ReceiptService:
    """Service for receipt processing"""

    def __init__(self):
        self.telegram = TelegramService()
        self.storage = StorageService()
        self.processor = DocumentProcessorService()

    def process_receipt(self, message: Dict, chat_id: int, is_store_raw_photo: bool = False) -> Dict:
        """Process receipt photo end-to-end with limit checking"""

        self.telegram.send_typing(chat_id)
        secure_user_id = get_secure_user_id(chat_id)

        # Download photo
        logger.info("Downloading receipt photo")
        photo_data = self.telegram.download_photo(message['photo'])
        if not photo_data:
            return self.telegram.send_error(chat_id, "העלאת התמונה נכשלה. נא לנסות שוב.")

        receipt_id = str(uuid.uuid4())
        image_url: str | None = None

        # Store raw image
        if is_store_raw_photo:
            logger.info(f"Storing receipt image with ID: {receipt_id} for user: {chat_id}")
            self.telegram.send_message(chat_id, "📁 שומר את התמונה...")
            image_url = self.storage.store_raw_image(receipt_id, photo_data)
            if not image_url:
                return self.telegram.send_error(chat_id, "שגיאה בשמירת התמונה. נא לנסות שוב.")

        # Analyze receipt using hybrid processor
        logger.info(f"Analyzing receipt with ID: {receipt_id}")
        self.telegram.send_message(chat_id, "🔍 מנתח את הקבלה...")
        analysis_result  = self.processor.process_receipt(photo_data)

        if not analysis_result:
            return self.telegram.send_error(
                chat_id,
                "❌ לא הצלחתי לעבד את הקבלה.\n\n"
                "יתכן שהתמונה לא ברורה מספיק או שהנתונים לא תקינים.\n"
                "נא לצלם שוב את הקבלה בתאורה טובה ולנסות שוב."
            )

        try:
            # Store validated data
            logger.info(f"Storing receipt data for ID: {receipt_id}")
            self.storage.store_receipt_data(receipt_id, secure_user_id, analysis_result.receipt_data, image_url)
            response_text = self._format_receipt_response(analysis_result, receipt_id)
            self.telegram.send_message(chat_id, response_text, parse_mode=None)

            return create_response(200, {"status": "success"})

        except ValueError as e:
            if str(e) == "DUPLICATE_RECEIPT":
                self.telegram.send_message(chat_id, "❌ קבלה זהה כבר קיימת במערכת")
                return create_response(200, {"status": "duplicate"})
            else:
                logger.error(f"Receipt validation error: {e}")
                return self.telegram.send_error(chat_id, "❌ שגיאה בנתוני הקבלה")

        except Exception as e:
            logger.error(f"Receipt processing error: {e}", exc_info=True)
            return self.telegram.send_error(chat_id, "שגיאה במהלך עיבוד הקבלה .")

    def _format_receipt_response(self, result: ReceiptAnalysisResult, receipt_id: str) -> str:
        """Format receipt data for Telegram with Hebrew support"""

        receipt_data = result.receipt_data

        try:
            response = "✅ ניתוח הקבלה הושלם\n\n"

            # Store info - no encoding/decoding needed for Hebrew
            if receipt_data.store_name:
                response += f"🏪 חנות : {receipt_data.store_name}\n"

            if receipt_data.purchasing_date:
                response += f"📅 תאריך : {receipt_data.purchasing_date}\n"

            if receipt_data.receipt_number:
                response += f"🧾 מס׳ קבלה : {receipt_data.receipt_number}\n"

            if receipt_data.payment_method:
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
                icon = payment_icons.get(receipt_data.payment_method, '💰')
                label = payment_labels.get(receipt_data.payment_method, receipt_data.payment_method)
                response += f"{icon} אמצעי תשלום : {label}\n"

            response += "\n"

            # Items section with proper price calculation

            if receipt_data.items:
                response += "📋 פריטים :\n"
                items_to_show = receipt_data.items[:MAX_ITEMS_DISPLAY]

                for item in items_to_show:
                    # Get item details
                    name = item.name

                    # Truncate long names
                    if len(name) > MAX_ITEM_NAME_LENGTH:
                        name = name[:MAX_ITEM_NAME_LENGTH-3] + "..."

                    actual_price = (float(item.price) * float(item.quantity)) + float(item.discount)

                    # Format the line
                    line = f"• {name}"

                    # Show quantity if not 1 (handle both int and float quantities)
                    if item.quantity != 1:
                        if item.quantity == int(item.quantity):
                            line += f" (x{int(item.quantity)})"
                        else:
                            line += f" ({item.quantity:.3f})"

                    # Show unit price
                    line += f" - ₪{actual_price:.2f}"

                    # Add category
                    line += f" [{category_manager.get_category_hebrew_name(item.category)}]"

                    response += line + "\n"

                # Show if more items exist
                if len(receipt_data.items) > MAX_ITEMS_DISPLAY:
                    response += f"... ועוד {len(receipt_data.items) - MAX_ITEMS_DISPLAY} פריטים \n"

            # Total section
            if receipt_data.total:
                response += f"\n💰 סה״כ : ₪{receipt_data.total:.2f}"

            response += "\n✅ נשמר בהצלחה במסד הנתונים"

            return response

        except Exception as e:
            logger.error(f"Formatting error: {e}")
            return f"✅ הקבלה עובדה בהצלחה! \n\n🆔 מזהה : `{receipt_id}`\n✅ נשמר במסד הנתונים"
