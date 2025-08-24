"""
    Message Queue Service module
"""

import json
import logging
from typing import Dict, Any
from datetime import datetime, timezone
from config import get_sqs_client, SQS_QUEUE_URL, setup_logging
from services.orchestrator_service import MessageType


setup_logging()
logger = logging.getLogger(__name__)

class MessageQueueService:
    """Service for queuing Telegram messages for async processing"""

    def __init__(self):
        self.sqs_client = get_sqs_client()
        self.queue_url = SQS_QUEUE_URL
        self.is_fifo = self.queue_url.endswith(".fifo")

    def queue_telegram_message(self, telegram_message: Dict[str, Any]) -> bool:
        """Queue raw Telegram message for processing by consumer lambda"""

        try:
            if not self.queue_url:
                logger.error("SQS_QUEUE_URL not configured")
                return False

            body = json.dumps(telegram_message)
            kwargs = {
                "QueueUrl": self.queue_url,
                "MessageBody": body,
                "MessageAttributes": {
                    "chat_id": {
                        "StringValue": str(telegram_message["chat"]["id"]),
                        "DataType": "String"
                    },
                    "media_group_id": {
                        "StringValue": str(telegram_message.get("media_group_id", "")),
                        "DataType": "String"
                    },
                    "message_type": {
                        "StringValue": telegram_message.get("photo") and "photo" or "other",
                        "DataType": "String"
                    }
                }
            }

            if self.is_fifo:
                # Use media_group_id for albums, fallback to chat_id for single messages
                kwargs["MessageGroupId"] = telegram_message.get("media_group_id") or str(telegram_message["chat"]["id"])

                # Deduplication: use update_id if present, else message_id
                kwargs["MessageDeduplicationId"] = str(telegram_message.get("update_id") or telegram_message.get("message_id"))

            response = self.sqs_client.send_message(**kwargs)
            logger.info(f"Queued message to SQS: {response.get('MessageId')}")
            return True

        except Exception as e:
            logger.error(f"Failed to queue Telegram message: {e}", exc_info=True)
            return False
