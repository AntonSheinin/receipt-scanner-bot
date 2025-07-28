"""
Main Telegram Lambda Handler - Entry Point
"""
import json
import logging
import os
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
        
        # Handle API Gateway health check
        if event.get('httpMethod') == 'GET':
            return create_response(200, {"status": "ok", "message": "Telegram webhook endpoint"})
        
        # Parse Telegram update
        body_str = event.get('body', '{}')
        if isinstance(body_str, str):
            body = json.loads(body_str)
        else:
            body = body_str
            
        logger.info(f"Parsed body: {json.dumps(body, default=str)}")
        
        if 'message' not in body:
            logger.info("No message in update, ignoring")
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
    elif text.lower() == '/webhook':
        # Admin command to check webhook status
        webhook_info = check_webhook_status()
        telegram_service.send_message(chat_id, f"🔗 Webhook Status:\n```{webhook_info}```")
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


def check_webhook_status() -> str:
    """Check current webhook status"""
    try:
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not bot_token:
            return "Bot token not configured"
        
        import requests
        response = requests.get(f"https://api.telegram.org/bot{bot_token}/getWebhookInfo")
        if response.status_code == 200:
            result = response.json().get('result', {})
            return (
                f"URL: {result.get('url', 'Not set')}\n"
                f"Pending: {result.get('pending_update_count', 0)}\n"
                f"Last Error: {result.get('last_error_message', 'None')}"
            )
        return f"Error: {response.status_code}"
    except Exception as e:
        return f"Error checking webhook: {e}"


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