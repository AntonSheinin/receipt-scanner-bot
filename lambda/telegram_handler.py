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

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Initialize services
telegram_service = TelegramService()
receipt_service = ReceiptService()
query_service = QueryService()


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main Lambda handler for Telegram webhook"""
    try:
        logger.info(f"Received event: {json.dumps(event, default=str)}")
        
        # Parse Telegram update
        body = json.loads(event.get('body', '{}'))
        if 'message' not in body:
            return create_response(200, {"status": "no message"})
        
        message = body['message']
        chat_id = message['chat']['id']
        
        # Route to appropriate service
        if 'photo' in message:
            return receipt_service.process_receipt(message, chat_id)
        elif 'text' in message:
            return process_text_message(message, chat_id)
        
        return create_response(200, {"status": "unsupported"})
        
    except Exception as e:
        logger.error(f"Handler error: {e}", exc_info=True)
        return create_response(500, {"error": str(e)})


def process_text_message(message: Dict, chat_id: int) -> Dict:
    """Route text messages to appropriate handler"""
    text = message.get('text', '').strip()
    
    if text.lower() in ['/start', '/help']:
        welcome_msg = get_welcome_message()
        telegram_service.send_message(chat_id, welcome_msg)
        return create_response(200, {"status": "handled"})
    else:
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
        "Just send a clear photo of your receipt! 📸"
    )


def create_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Create Lambda response"""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body)
    }