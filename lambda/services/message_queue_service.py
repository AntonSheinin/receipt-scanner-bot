"""
    Message Queue Service module
"""

import json
import logging
from typing import Dict, Any
from datetime import datetime, timezone
from config import get_sqs_client, SQS_QUEUE_URL, setup_logging


setup_logging()
logger = logging.getLogger(__name__)

class MessageQueueService:
    """Service for queuing Telegram messages for async processing"""

    def __init__(self):
        self.sqs_client = get_sqs_client()
        self.queue_url = SQS_QUEUE_URL

    def queue_telegram_message(self, telegram_message: Dict[str, Any]) -> bool:
        """Queue raw Telegram message for processing by consumer lambda"""
        try:
            if not self.queue_url:
                logger.error("SQS_QUEUE_URL not configured")
                return False

            # Create queue payload with raw Telegram message
            queue_payload = {
                "telegram_message": telegram_message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "chat_id": telegram_message['chat']['id']
            }

            response = self.sqs_client.send_message(
                QueueUrl=self.queue_url,
                MessageBody=json.dumps(queue_payload, default=str),
                MessageAttributes={
                    'ChatId': {
                        'StringValue': str(telegram_message['chat']['id']),
                        'DataType': 'String'
                    },
                    'MessageType': {
                        'StringValue': self._detect_message_type(telegram_message),
                        'DataType': 'String'
                    }
                }
            )

            logger.info(f"Queued Telegram message for chat_id: {telegram_message['chat']['id']}, MessageId: {response.get('MessageId')}")
            return True

        except Exception as e:
            logger.error(f"Failed to queue Telegram message: {e}")
            return False

    def _detect_message_type(self, telegram_message: Dict[str, Any]) -> str:
        """Detect message type for SQS attributes"""
        if 'photo' in telegram_message:
            return 'photo'
        elif 'text' in telegram_message:
            text = telegram_message.get('text', '').strip().lower()
            if text.startswith('/'):
                return 'command'
            else:
                return 'text_query'
        else:
            return 'unknown'
