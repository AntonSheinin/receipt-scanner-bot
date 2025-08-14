# lambda/consumer_handler.py - NEW FILE
"""
Consumer Lambda - Processes SQS Messages via Orchestration Service
"""
import json
import logging
from typing import Dict, Any

from config import setup_logging
from services.orchestrator_service import OrchestratorService

setup_logging()
logger = logging.getLogger(__name__)

# Initialize orchestrator service
orchestrator_service = OrchestratorService()

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Consumer Lambda - Processes SQS messages using OrchestratorService
    """

    logger.info(f"Consumer processing {len(event.get('Records', []))} SQS messages")

    processed_count = 0
    failed_count = 0
    results = []

    for record in event.get('Records', []):
        try:
            # Parse the SQS message
            message_body = json.loads(record['body'])
            telegram_message = message_body['telegram_message']
            timestamp = message_body.get('timestamp')
            chat_id = telegram_message['chat']['id']

            logger.info(f"Processing message for chat_id: {chat_id} (queued at: {timestamp})")

            # Use OrchestratorService to process the message
            result = orchestrator_service.process_telegram_message(telegram_message)

            results.append({
                "chat_id": chat_id,
                "status": "success",
                "result": result
            })

            processed_count += 1
            logger.info(f"Successfully processed message for chat_id: {chat_id}")

        except Exception as e:
            logger.error(f"Failed to process SQS message: {e}", exc_info=True)
            failed_count += 1

            # Try to extract chat_id for error reporting
            try:
                chat_id = json.loads(record['body'])['telegram_message']['chat']['id']
                results.append({
                    "chat_id": chat_id,
                    "status": "error",
                    "error": str(e)
                })
            except:
                results.append({
                    "status": "error",
                    "error": f"Failed to parse message: {str(e)}"
                })

    # Prepare response
    response = {
        "statusCode": 200,
        "processed": processed_count,
        "failed": failed_count,
        "total": len(event.get('Records', [])),
        "results": results
    }

    logger.info(f"Consumer batch processing complete: processed={processed_count}, failed={failed_count}")

    # If any messages failed, log details but don't fail the entire batch
    if failed_count > 0:
        logger.warning(f"Some messages failed processing: {failed_count}/{len(event.get('Records', []))}")

    return response
