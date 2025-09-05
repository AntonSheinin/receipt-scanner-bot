"""
    Producer Lambda - Telegram Bot Handler
"""

import json
import logging
from config import setup_logging
from services.telegram_service import TelegramService
from services.message_queue_service import MessageQueueService
from providers.helpers import create_response


setup_logging()
logger = logging.getLogger(__name__)

# Track processed updates to avoid duplicates
_processed_updates = set()

# Initialize only services needed for webhook handling
telegram_service = TelegramService()
queue_service = MessageQueueService()

def lambda_handler(event: dict, context) -> dict | None:
    """Producer Lambda - Only queues messages, no processing"""

    logger.info(f"Producer received webhook: {json.dumps(event, default=str)}")

    # Handle API Gateway health check
    if event.get('httpMethod') == 'GET':
        return create_response(200, {"status": "ok", "message": "Telegram webhook endpoint"})

    # Parse body
    raw_body = event.get("body")
    if not raw_body:
        logger.error("No body in event")
        return create_response(200, {"status": "No body in event"})

    body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body
    update_id = body.get("update_id")

    # Simple deduplication check
    if update_id and update_id in _processed_updates:
        logger.info(f"Update {update_id} already processed, skipping")
        return create_response(200, {"status": "duplicate"})

    # Mark as processed
    if update_id:
        _processed_updates.add(update_id)
        if len(_processed_updates) > 1000:
            _processed_updates.clear()

    message = body.get('message')
    if not message:
        logger.error("No message in body")
        return create_response(200, {"status": "no message"})

    chat_id = message['chat']['id']

    try:
        # Send immediate acknowledgment to user
        telegram_service.send_typing(chat_id)
        telegram_service.send_message(chat_id, "📨 קיבלתי את ההודעה! מעבד...")

        # Queue the entire Telegram message for processing
        success = queue_service.queue_telegram_message(message)

        if success:
            logger.info(f"Successfully queued message for chat_id: {chat_id}")
            return create_response(200, {"status": "queued_successfully"})

        else:
            # If queuing fails, notify user
            telegram_service.send_message(chat_id, "❌ הייתה בעיה זמנית. אנא נסה שוב.")
            return create_response(500, {"status": "queue_failed"})

    except Exception as e:
        logger.error(f"Producer error for chat_id {chat_id}: {e}", exc_info=True)
        try:
            telegram_service.send_message(chat_id, "❌ הייתה בעיה זמנית. אנא נסה שוב.")
        except:
            pass
        return create_response(500, {"status": "error"})
