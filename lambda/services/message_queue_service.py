"""
    Message Queue Service module
"""

import json
import logging
from typing import Dict, Any
from config import get_sqs_client, SQS_QUEUE_URL, setup_logging
from services.orchestrator_service import MessageType


setup_logging()
logger = logging.getLogger(__name__)

class MessageQueueService:
    """Service for queuing Telegram messages for async processing"""

    def __init__(self):
        self.sqs_client = get_sqs_client()
        self.queue_url = SQS_QUEUE_URL

    def _get_message_type(self, telegram_message: Dict[str, Any]) -> MessageType:
        """Extract message type from Telegram message"""

        if "photo" in telegram_message:
            return MessageType.PHOTO.value

        if "text" in telegram_message:
            text = telegram_message.get("text", "").strip()
            if text.startswith("/"):
                return MessageType.COMMAND.value

            return MessageType.TEXT_QUERY.value

        return MessageType.UNKNOWN.value

    def queue_telegram_message(self, telegram_message: Dict[str, Any]) -> bool:
        """Queue raw Telegram message for processing by consumer lambda"""

        try:
            if not self.queue_url:
                logger.error("SQS_QUEUE_URL not configured")
                return False

            chat_id = str(telegram_message['chat']['id'])
            media_group_id = str(telegram_message.get("media_group_id", chat_id))

            body = json.dumps(telegram_message)
            kwargs = {
                "QueueUrl": self.queue_url,
                "MessageBody": body,
                "MessageGroupId": media_group_id,
                "MessageDeduplicationId": str(telegram_message.get("update_id") or telegram_message.get("message_id")),
                "MessageAttributes": {
                    "chat_id": {
                        "StringValue": chat_id,
                        "DataType": "String"
                    },
                    "message_type": {
                        "StringValue": self._get_message_type(telegram_message),
                        "DataType": "String"
                    },
                }
            }

            response = self.sqs_client.send_message(**kwargs)
            logger.info(f"Queued message to SQS: {response.get('MessageId')}")
            return True

        except Exception as e:
            logger.error(f"Failed to queue Telegram message: {e}", exc_info=True)
            return False
