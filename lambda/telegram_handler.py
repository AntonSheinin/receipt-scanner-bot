"""
Main Telegram Lambda Handler - Entry Point
"""
import json
import logging
from typing import Dict, Any

from config import setup_logging
from services.receipt_service import ReceiptService
from services.query_service import QueryService
from services.telegram_service import TelegramService


setup_logging()
logger = logging.getLogger(__name__)

# Initialize services
telegram_service = TelegramService()
receipt_service = ReceiptService()
query_service = QueryService()

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main Lambda handler for Telegram"""
    try:
        logger.info(f"Received event: {json.dumps(event, default=str)}")
        
        # Handle API Gateway health check
        if event.get('httpMethod') == 'GET':
            return create_response(200, {"status": "ok", "message": "Telegram webhook endpoint"})
        
        # Parse Telegram update
        body = event.get('body', '{}')
        if isinstance(body, str):
            body = json.loads(body)
        logger.info(f"Parsed body: {json.dumps(body, default=str)}")

        message = body.get('message')
        if not message:
            logger.info("No message in update, ignoring")
            return create_response(200, {"status": "no message"})
        
        # Process message after responding to Telegram
        chat_id = message['chat']['id']
        try:
            if 'photo' in message:
                process_receipt_async(message, chat_id)
            elif 'text' in message:
                process_text_message(message, chat_id)
        except Exception as e:
            logger.error(f"Processing error: {e}", exc_info=True)
            telegram_service.send_message(chat_id, "❌ An error occurred while processing your request.")
            
        return create_response(200, {"status": "processing"})

    except Exception as e:
        logger.error(f"Handler error: {e}", exc_info=True)
        return create_response(200, {"status": "error"})  # Always return 200 to prevent retries
    
def process_receipt_async(message: Dict, chat_id: int) -> None:
    """Process receipt asynchronously after responding to Telegram"""
    try:   
        receipt_service.process_receipt(message, chat_id)

    except Exception as e:
        logger.error(f"Async receipt processing error: {e}", exc_info=True)
        try:
            telegram_service.send_message(chat_id, "❌ Failed to process receipt. Please try again.")
        except:
            pass

def process_text_message(message: Dict, chat_id: int) -> Dict:
    """Route text messages to appropriate handler"""
    text = message.get('text', '').strip()
    lower_text = text.lower()
    
    if lower_text in ('/start', '/help'):
        telegram_service.send_message(chat_id, get_welcome_message())
        return create_response(200, {"status": "handled"})
    
    if lower_text == '/delete_last':
        return handle_delete_last_command(chat_id)
    
    if lower_text == '/delete_all':
        return handle_delete_all_command(chat_id)
    
    return query_service.process_query(text, str(chat_id))


def get_welcome_message() -> str:
    """Get welcome message for bot"""
    return (
        "🧾 *Receipt Recognition Bot*\n\n"
        "Send me a photo of your receipt and I'll extract the structured data!\n\n"
        "I can recognize:\n"
        "• Store name\n"
        "• Date\n" 
        "• Receipt number\n"
        "• Items with prices\n"
        "• Total amount\n\n"
        "💾 Your receipts are automatically stored and you'll get a unique ID for each one.\n\n"
        "📊 *Ask me questions like:*\n"
        "• \"How much did I spend on food in August?\"\n"
        "• \"Which store has the cheapest milk?\"\n"
        "• \"Show me all receipts from Rami Levy\"\n"
        "• \"How many times did I shop last month?\"\n\n"
        "🤖 *Available Commands:*\n"
        "• /start - Show this welcome message\n"
        "• /help - Show this help information\n"
        "• /delete_last - Delete your most recent receipt\n"
        "• /delete_all - Delete all your receipts\n\n"
        "💡 *Tip:* Type '/' to see all available commands in the menu!\n\n"
        "Just send a clear photo of your receipt! 📸"
    )

def create_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Create Lambda response in API Gateway format"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(body),
        "isBase64Encoded": False
    }

def handle_delete_last_command(chat_id: int) -> Dict:
    """Handle /delete_last command - delete last UPLOADED receipt"""
    try:
        from services.storage_service import StorageService
        storage_service = StorageService()
        
        telegram_service.send_typing(chat_id)
        
        # Make sure we delete by upload date (created_at), not receipt date
        deleted_receipt = storage_service.delete_last_receipt(str(chat_id))
        
        if deleted_receipt:
            store_name = deleted_receipt.get('store_name', 'Unknown Store')
            receipt_date = deleted_receipt.get('date', 'Unknown Date')
            upload_date = deleted_receipt.get('created_at', 'Unknown Upload Date')
            total = deleted_receipt.get('total', '0.00')
            
            message = (
                "🗑️ *Last Uploaded Receipt Deleted*\n\n"
                f"🏪 Store: {store_name}\n"
                f"📅 Receipt Date: {receipt_date}\n"
                f"📤 Uploaded: {upload_date[:10]}\n"  # Show just date part
                f"💰 Total: ${total}\n"
                f"🆔 Receipt ID: `{deleted_receipt['receipt_id']}`"
            )
        else:
            message = "❌ No receipts found to delete. Upload some receipts first!"
        
        telegram_service.send_message(chat_id, message)
        return create_response(200, {"status": "handled"})
        
    except Exception as e:
        logger.error(f"Delete last command error: {e}")
        telegram_service.send_message(chat_id, "❌ Error deleting receipt. Please try again.")
        return create_response(200, {"status": "error"})

def handle_delete_all_command(chat_id: int) -> Dict:
    """Handle /delete-all command"""
    try:
        from services.storage_service import StorageService
        storage_service = StorageService()
        
        telegram_service.send_typing(chat_id)
        telegram_service.send_message(chat_id, "🗑️ Deleting all receipts... Please wait.")
        
        deleted_count = storage_service.delete_all_receipts(str(chat_id))
        
        if deleted_count > 0:
            message = (
                "🗑️ *All Receipts Deleted Successfully*\n\n"
                f"📊 Total deleted: {deleted_count} receipts\n"
                "💾 All associated images have been removed from storage"
            )
        else:
            message = "❌ No receipts found to delete. Your storage is already empty!"
        
        telegram_service.send_message(chat_id, message)
        return create_response(200, {"status": "handled"})
        
    except Exception as e:
        logger.error(f"Delete all command error: {e}")
        telegram_service.send_message(chat_id, "❌ Error deleting receipts. Please try again.")
        return create_response(200, {"status": "error"})