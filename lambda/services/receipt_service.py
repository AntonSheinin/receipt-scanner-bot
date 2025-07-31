"""
Receipt Processing Service
"""
import logging
import uuid
from typing import Dict

from .telegram_service import TelegramService
from .storage_service import StorageService
from utils.llm_client import LLMClient
from utils.helpers import create_response
from config import MAX_ITEMS_DISPLAY, MAX_ITEM_NAME_LENGTH, setup_logging


setup_logging()
logger = logging.getLogger(__name__)

class ReceiptService:
    """Service for receipt processing"""
    
    def __init__(self):
        self.telegram = TelegramService()
        self.storage = StorageService()
        self.llm = LLMClient()
    
    def process_receipt(self, message: Dict, chat_id: int) -> Dict:
        """Process receipt photo end-to-end"""
        try:
            self.telegram.send_typing(chat_id)
            
            # Download photo
            photo_data = self.telegram.download_photo(message['photo'])
            if not photo_data:
                return self.telegram.send_error(chat_id, "Failed to download image. Please try again.")
            
            receipt_id = str(uuid.uuid4())
            user_id = str(chat_id)
            
            # Store image
            self.telegram.send_message(chat_id, "📁 Storing image...")
            image_url = self.storage.store_image(receipt_id, photo_data)
            if not image_url:
                return self.telegram.send_error(chat_id, "Failed to store image. Please try again.")
            
            # Analyze receipt
            self.telegram.send_message(chat_id, "🔍 Analyzing receipt... Please wait.")
            receipt_data = self.llm.analyze_receipt(photo_data)
            if not receipt_data:
                return self.telegram.send_error(chat_id, "Could not process receipt. Please ensure the image is clear and contains a valid receipt.")
            
            # Store data and respond
            self.storage.store_receipt_data(receipt_id, user_id, receipt_data, image_url)
            response_text = self._format_receipt_response(receipt_data, receipt_id)
            self.telegram.send_message(chat_id, response_text)
            
            return create_response(200, {"status": "success"})
            
        except Exception as e:
            logger.error(f"Receipt processing error: {e}", exc_info=True)
            return self.telegram.send_error(chat_id, "An error occurred while processing your receipt.")
    
    def _format_receipt_response(self, receipt_data: Dict, receipt_id: str) -> str:
        """Format receipt data for Telegram"""
        try:
            result = "✅ *Receipt Analysis Complete*\n\n"
            
            # Store info
            if receipt_data.get('store_name'):
                store_name = receipt_data['store_name']
                if isinstance(store_name, str):
                    store_name = store_name.encode('utf-8').decode('utf-8')
                result += f"🏪 *Store:* {store_name}\n"
            
            if receipt_data.get('date'):
                result += f"📅 *Date:* {receipt_data['date']}\n"
            
            if receipt_data.get('receipt_number'):
                result += f"🧾 *Receipt #:* {receipt_data['receipt_number']}\n"

            if receipt_data.get('payment_method'):
                payment_icons = {
                    'cash': '💵',
                    'credit_card': '💳', 
                    'other': '💰'
                }
                method = receipt_data['payment_method']
                icon = payment_icons.get(method, '💰')
                result += f"{icon} *Payment:* {method.replace('_', ' ').title()}\n"
            
            result += "\n"
            
            # Items (limit to prevent overflow)
            items = receipt_data.get('items', [])
            if items:
                result += "*📋 Items:*\n"
                items_to_show = items[:MAX_ITEMS_DISPLAY]
                
                for item in items_to_show:
                    name = item.get('name', 'Unknown item')
                    if isinstance(name, str):
                        name = name.encode('utf-8').decode('utf-8')
                    
                    if len(name) > MAX_ITEM_NAME_LENGTH:
                        name = name[:MAX_ITEM_NAME_LENGTH-3] + "..."
                    
                    price = item.get('price', 0)
                    try:
                        quantity = int(item.get('quantity', 1))
                    except (ValueError, TypeError):
                        quantity = 1
                    category = item.get('category', '')
                    
                    line = f"• {name}"
                    if quantity > 1:
                        line += f" (x{quantity})"
                    line += f" - ${price}"
                    if category:
                        line += f" `[{category}]`"
                    result += line + "\n"
                
                if len(items) > MAX_ITEMS_DISPLAY:
                    result += f"... and {len(items) - MAX_ITEMS_DISPLAY} more items\n"
            
            # Total and receipt ID
            if receipt_data.get('total'):
                result += f"\n💰 *Total:* ${receipt_data['total']}"
            
            result += f"\n\n🆔 *Receipt ID:* `{receipt_id}`"
            result += f"\n✅ *Stored successfully in database*"
            
            return result
            
        except Exception as e:
            logger.error(f"Formatting error: {e}")
            return f"✅ Receipt processed successfully!\n\n🆔 *Receipt ID:* `{receipt_id}`\n✅ *Stored in database*"