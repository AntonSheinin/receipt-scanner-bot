"""
Main Telegram Lambda Handler - Entry Point
"""
import json
import logging
from typing import Dict, Any, Optional

from config import setup_logging
from services.receipt_service import ReceiptService
from services.query_service import QueryService
from services.telegram_service import TelegramService
from services.storage_service import StorageService


setup_logging()
logger = logging.getLogger(__name__)

# Track processed updates to avoid duplicates
_processed_updates = set()

# Initialize services
telegram_service = TelegramService()
receipt_service = ReceiptService()
query_service = QueryService()
storage_service = StorageService()

def lambda_handler(event: Dict[str, Any], context: Any) -> Optional[Dict[str, Any]]:
    """Main Lambda handler for Telegram"""

    logger.info(f"Received event: {json.dumps(event, default=str)}")

    # Parse update_id for deduplication
    body = json.loads(event.get('body', '{}')) if event.get('body') else {}
    update_id = body.get('update_id')

    # Simple deduplication check
    if update_id and update_id in _processed_updates:
        logger.info(f"Update {update_id} already processed, skipping")
        return create_response(200, {"status": "duplicate"})

    # Mark as processed
    if update_id:
        _processed_updates.add(update_id)
        # Keep cache small
        if len(_processed_updates) > 1000:
            _processed_updates.clear()

    # Handle API Gateway health check
    if event.get('httpMethod') == 'GET':
        return create_response(200, {"status": "ok", "message": "Telegram webhook endpoint"})

    # Parse Telegram update
    raw_body = event.get('body')
    body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body
    if not body:
        logger.error("No body in event, ignoring")
        return create_response(200, {"status": "No body in event"})

    logger.info(f"Parsed body: {json.dumps(body, default=str)}")

    message = body.get('message')
    if not message:
        logger.error("No message in body, ignoring")
        return create_response(200, {"status": "no message"})

    # Process message after responding to Telegram
    chat_id = message['chat']['id']

    text = message.get('text', '').strip().lower()

    if text in ('/start', '/help'):
        logger.info("Handling /start or /help command")
        telegram_service.send_message(chat_id, get_welcome_message())
        return create_response(200, {"status": "handled welcome message"})

    elif text == '/delete_last':
        logger.info("Handling /delete_last command")
        return handle_delete_last_command(chat_id)

    elif text == '/delete_all':
        logger.info("Handling /delete_all command")
        return handle_delete_all_command(chat_id)

    elif 'photo' in message:
        logger.info("Processing receipt photo")
        telegram_service.send_typing(chat_id)
        telegram_service.send_message(chat_id, "📸 Processing your receipt... Please wait.")

        try:
            receipt_service.process_receipt(message, chat_id)

        except Exception as e:
            logger.error(f"Receipt processing error: {e}", exc_info=True)
            telegram_service.send_message(chat_id, "❌ Failed to process receipt. Please try again.")

    elif 'text' in message:
        logger.info("Processing query message")
        telegram_service.send_typing(chat_id)
        telegram_service.send_message(chat_id, "🔍 Processing your query... Please wait.")

        try:
            query_service.process_query(text, str(chat_id))

        except Exception as e:
            logger.error(f"Query processing error: {e}", exc_info=True)
            telegram_service.send_message(chat_id, "❌ Failed to process your query. Please try again.")

        return create_response(200, {"status": "processing"})

def get_welcome_message() -> str:
    """Get welcome message for bot"""
    return (
        "🧾 *Receipt Scanner Bot*\n\n"
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

    telegram_service.send_typing(chat_id)

    # Make sure we delete by upload date (created_at), not receipt date
    deleted_receipt = storage_service.delete_last_uploaded_receipt(str(chat_id))

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

        logger.info(f"Deleted last uploaded receipt {deleted_receipt['receipt_id']}")

    else:
        logger.info("No receipts found to delete")
        message = "❌ No receipts found to delete. Upload some receipts first!"

    telegram_service.send_message(chat_id, message)
    return create_response(200, {"status": "delete_last_command_handled"})

def handle_delete_all_command(chat_id: int) -> Dict:
    """Handle /delete-all command"""

    telegram_service.send_typing(chat_id)
    telegram_service.send_message(chat_id, "🗑️ Deleting all receipts... Please wait.")

    deleted_count = storage_service.delete_all_receipts(str(chat_id))

    if deleted_count > 0:
        message = (
            "🗑️ *All Receipts Deleted Successfully*\n\n"
            f"📊 Total deleted: {deleted_count} receipts\n"
            "💾 All associated images have been removed from storage"
        )

        logger.info(f"Deleted {deleted_count} receipts")

    else:
        message = "❌ No receipts found to delete. Your storage is already empty!"
        logger.info("No receipts found to delete")

    telegram_service.send_message(chat_id, message)
    return create_response(200, {"status": "delete_all_command_handled"})
