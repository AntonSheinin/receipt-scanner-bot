"""
    Consumer Lambda - Processes SQS Messages via OrchestratorService (FIFO aware, album batching)
"""

import json
import logging
from collections import defaultdict
from typing import Dict, Any
from config import setup_logging
from services.orchestrator_service import OrchestratorService

setup_logging()
logger = logging.getLogger(__name__)

orchestrator_service = OrchestratorService()


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
        Processes SQS messages sequentially (FIFO) and batches album messages by media_group_id.
        Single messages are processed immediately.
    """

    records = event.get("Records", [])
    logger.info(f"Consumer processing {len(records)} SQS messages")

    processed_count = 0
    failed_count = 0
    results = []

    # Group album messages by media_group_id
    album_batches = defaultdict(list)
    single_messages = []

    for record in records:
        try:
            message_body = json.loads(record["body"])
            attrs = record.get("messageAttributes", {})

            chat_id = int(attrs.get("chat_id", {}).get("stringValue", 0))
            media_group_id = attrs.get("media_group_id", {}).get("stringValue")
            message_type = attrs.get("message_type", {}).get("stringValue", "other")

            # Inject message_type into body
            message_body["message_type"] = message_type

            if media_group_id:
                album_batches[media_group_id].append(message_body)

            else:
                single_messages.append(message_body)

        except Exception as e:
            logger.error(f"Failed to parse SQS message: {e}", exc_info=True)
            failed_count += 1
            results.append({
                "chat_id": chat_id if "chat_id" in locals() else None,
                "status": "error",
                "error": str(e)
            })

    # Process single messages immediately
    for message in single_messages:
        try:
            chat_id = message["chat"]["id"]
            result = orchestrator_service.process_telegram_message(message)
            results.append({"chat_id": chat_id, "status": "success", "result": result})
            processed_count += 1
        except Exception as e:
            logger.error(f"Failed processing single message for chat_id {chat_id}: {e}", exc_info=True)
            failed_count += 1
            results.append({"chat_id": chat_id, "status": "error", "error": str(e)})

    # Process album batches
    for media_group_id, messages in album_batches.items():
        try:
            chat_id = messages[0]["chat"]["id"]  # All messages in the album share the same chat_id
            logger.info(f"Processing album {media_group_id} with {len(messages)} messages for chat_id {chat_id}")
            result = orchestrator_service.process_telegram_album(messages)
            results.append({"chat_id": chat_id, "status": "success", "result": result})
            processed_count += len(messages)
        except Exception as e:
            logger.error(f"Failed processing album {media_group_id}: {e}", exc_info=True)
            failed_count += len(messages)
            results.append({"chat_id": chat_id, "status": "error", "error": str(e)})

    response = {
        "statusCode": 200,
        "processed": processed_count,
        "failed": failed_count,
        "total": len(records),
        "results": results
    }

    logger.info(f"Consumer batch complete: processed={processed_count}, failed={failed_count}")
    return response
