"""
    Consumer Lambda - Processes SQS Messages with Album Support
"""

import json
import logging
import io
import base64
from typing import Dict, Any
from config import setup_logging, get_s3_client, S3_BUCKET_NAME
from services.orchestrator_service import OrchestratorService
from services.telegram_service import TelegramService
from services.receipt_service import ReceiptService
from botocore.exceptions import ClientError
from providers.image_preprocessor.pillow_preprocessor import SimpleImageStitching
from services.llm_service import LLMService
from config import LLM_PROVIDER
from providers.image_preprocessor.pillow_preprocessor import IntelligentReceiptStitcher


setup_logging()
logger = logging.getLogger(__name__)

# Initialize services once
orchestrator_service = OrchestratorService()
telegram_service = TelegramService()
receipt_service = ReceiptService()
s3_client = get_s3_client()


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Process SQS messages - handles both single and album photos"""

    records = event.get("Records", [])
    logger.info(f"Consumer processing {len(records)} SQS messages")

    processed_count = 0
    failed_count = 0
    results = []

    # Process each message
    for record in records:
        try:
            message_body = json.loads(record["body"])
            message_attributes = record["messageAttributes"]
            message_group_id = record["attributes"]["MessageGroupId"]

            chat_id = int(message_attributes["chat_id"]["stringValue"])
            message_type = message_attributes["message_type"]["stringValue"]

            # Inject metadata into message
            message_body["message_type"] = message_type
            message_body["chat_id"] = chat_id

            logger.info(f"Processing message for chat_id: {chat_id}, message_group_id: {message_group_id}")

            # Check if this is an album photo (media_group_id != chat_id and is photo)
            is_album = message_group_id != str(chat_id) and message_type == "photo"

            if is_album:
                result = handle_album_photo(chat_id, message_group_id, message_body)
            else:
                # Process as single message
                result = orchestrator_service.process_telegram_message(message_body)

            results.append({
                "chat_id": chat_id,
                "status": "success",
                "result": result
            })
            processed_count += 1

        except Exception as e:
            logger.error(f"Failed processing message: {e}", exc_info=True)
            failed_count += 1
            results.append({
                "chat_id": chat_id if 'chat_id' in locals() else None,
                "status": "error",
                "error": str(e)
            })

    response = {
        "statusCode": 200,
        "processed": processed_count,
        "failed": failed_count,
        "total": len(records),
        "results": results
    }

    logger.info(f"Consumer batch complete: processed={processed_count}, failed={failed_count}")
    return response


def handle_album_photo(chat_id: int, media_group_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
    """Handle album photo with S3-based collection"""

    album_prefix = f"albums/{chat_id}/{media_group_id}/"
    first_photo_key = f"{album_prefix}first.jpg"

    try:
        # Check if first photo exists
        try:
            s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=first_photo_key)
            first_exists = True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                first_exists = False
            else:
                # Unexpected error
                raise

        if not first_exists:
            # First photo - store it
            photo_bytes = telegram_service.download_photo(message["photo"])
            if not photo_bytes:
                return {"status": "error", "error": "Failed to download photo"}

            s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=first_photo_key,
                Body=photo_bytes,
                ContentType="image/jpeg"
            )

            telegram_service.send_message(chat_id, "📸 קיבלתי תמונה ראשונה, ממתין לשנייה...")
            logger.info(f"Stored first photo for album {media_group_id}")
            return {"status": "stored_first_photo"}

        else:
            # Second photo - process album
            return process_album(chat_id, first_photo_key, message)

    except Exception as e:
        logger.error(f"Album handling error: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


def process_album(chat_id: int, first_photo_key: str, second_message: Dict[str, Any]) -> Dict[str, Any]:
    """Stitch two photos and process as single receipt"""

    try:
        # Download second photo
        second_photo_bytes = telegram_service.download_photo(second_message["photo"])
        if not second_photo_bytes:
            return {"status": "error", "error": "Failed to download second photo"}

        # Get first photo from S3
        first_photo_obj = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=first_photo_key)
        first_photo_bytes = first_photo_obj["Body"].read()

        logger.info("Got both photos, stitching...")
        telegram_service.send_message(chat_id, "🔄 מחבר את התמונות...")

        # ---------------------------Stiching photos--------------------------------

        # Get base64 encoded images
        img1_b64 = base64.b64encode(first_photo_bytes).decode('utf-8')
        img2_b64 = base64.b64encode(second_photo_bytes).decode('utf-8')

        stitcher = IntelligentReceiptStitcher()
        llm_service = LLMService(LLM_PROVIDER)
        plan = llm_service.generate_stitching_plan(img1_b64, img2_b64)
        stitched_bytes = stitcher.stitch_with_plan(first_photo_bytes, second_photo_bytes, plan)

        # --------------------------------------------------------------------------

        # TESTING: Send stitched photo back to user for visual verification
        logger.info("TESTING MODE: Sending stitched photo back to user")

        # Convert bytes to file-like object for Telegram API
        photo_file = io.BytesIO(stitched_bytes)
        photo_file.name = 'stitched_receipt.jpg'  # Telegram needs a filename

        telegram_service.send_photo(
            chat_id,
            photo_file,
            caption="✅ תמונות חוברו בהצלחה! (מצב בדיקה - הקבלה לא עובדה)"
        )
        result = {"status": "test_mode", "action": "returned_stitched_photo"}

        # TODO: Uncomment for production
        # result = receipt_service.process_receipt_from_bytes(stitched_bytes, chat_id)

        # Cleanup
        try:
            s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=first_photo_key)
            logger.info(f"Cleaned up: {first_photo_key}")
        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")

        return {"status": "album_processed", "result": result or {"status": "processed"}}

    except Exception as e:
        logger.error(f"Album processing error: {e}", exc_info=True)
        telegram_service.send_message(chat_id, "❌ שגיאה בעיבוד התמונות")
        return {"status": "error", "error": str(e)}
