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
from config import MAX_RECEIPTS_PER_USER
from utils.helpers import get_secure_user_id


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
        telegram_service.send_message(chat_id, "📸 מעבדים את הקבלה... נא להמתין")

        try:
            receipt_service.process_receipt(message, chat_id)

        except Exception as e:
            logger.error(f"Receipt processing error: {e}", exc_info=True)
            telegram_service.send_message(chat_id, "❌ לא הצלחנו לעבד את הקבלה. אנא נסה שוב.")

    elif 'text' in message:
        logger.info("Processing query message")
        telegram_service.send_typing(chat_id)
        telegram_service.send_message(chat_id, "🔍 מעבדים את שאלתך... נא להמתין.")

        try:
            query_service.process_query(text, chat_id)

        except Exception as e:
            logger.error(f"Query processing error: {e}", exc_info=True)
            telegram_service.send_message(chat_id, "❌ לא הצלחנו לעבד את השאלתך. אנא נסה שוב.")

        return create_response(200, {"status": "processing"})

def get_welcome_message() -> str:
    """Get welcome message for bot"""
    return (
    "🧾 בוט סורק קבלות \n\n"
    "שלח לי תמונה של הקבלה ואני אחלץ את המידע המובנה!\n\n"
    "אני יכול לזהות:\n"
    "• שם החנות\n"
    "• תאריך\n"
    "• מספר קבלה\n"
    "• פריטים עם מחירים\n"
    "• סכום כולל\n\n"
    "💾 הקבלות שלך נשמרות במאגר ללא מידע אישי .\n\n"
    f"📊 מגבלת אחסון: {MAX_RECEIPTS_PER_USER} קבלות לכל משתמש\n"
    "📊 שאל אותי שאלות כמו:\n"
    "• \"כמה הוצאתי על אוכל באוגוסט?\"\n"
    "• \"איזו חנות הכי זולה לחלב?\"\n"
    "• \"הראה לי את כל הקבלות מרמי לוי\"\n"
    "• \"כמה פעמים קניתי בחודש שעבר?\"\n\n"
    "🤖 פקודות זמינות:\n"
    "• /start - הצג הודעת ברוכים הבאים\n"
    "• /help - הצג מידע עזרה\n"
    "• /delete_last - מחק את הקבלה האחרונה שלך\n"
    "• /delete_all - מחק את כל הקבלות שלך\n\n"
    "💡 טיפ: הקלד '/' כדי לראות את כל הפקודות הזמינות בתפריט!\n\n"
    "פשוט שלח תמונה ברורה של הקבלה שלך! 📸"
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
    secure_user_id = get_secure_user_id(chat_id)

    # Make sure we delete by upload date (created_at), not receipt date
    deleted_receipt = storage_service.delete_last_uploaded_receipt(secure_user_id)

    if deleted_receipt:
        store_name = deleted_receipt.get('store_name', 'Unknown Store')
        receipt_date = deleted_receipt.get('date', 'Unknown Date')
        upload_date = deleted_receipt.get('created_at', 'Unknown Upload Date')
        total = deleted_receipt.get('total', '0.00')

        message = (
            "🗑️ הקבלה האחרונה נמחקה בהצלחה\n\n"
            f"🏪 חנות: {store_name}\n"
            f"📅 תאריך קבלה: {receipt_date}\n"
            f"📤 תאריך העלאה: {upload_date[:10]}\n"  # Show just date part
            f"💰 סך הכל: {total} שח \n"
            f"🆔 מזהה קבלה: `{deleted_receipt['receipt_id']}`"
        )

        logger.info(f"Deleted last uploaded receipt {deleted_receipt['receipt_id']}")

    else:
        logger.info("No receipts found to delete")
        message = "❌ לא נמצאו קבלות למחיקה. אין קבלות שמורות כרגע."

    telegram_service.send_message(chat_id, message)
    return create_response(200, {"status": "delete_last_command_handled"})

def handle_delete_all_command(chat_id: int) -> Dict:
    """Handle /delete-all command"""

    telegram_service.send_typing(chat_id)
    telegram_service.send_message(chat_id, "🗑️ מוחקים את כל הקבלות... נא להמתין.")

    secure_user_id = get_secure_user_id(chat_id)
    deleted_count = storage_service.delete_all_receipts(secure_user_id)

    if deleted_count > 0:
        message = (
            "🗑️ כל הקבלות נמחקו בהצלחה\n\n"
            f"📊 סך הכל נמחקו: {deleted_count} קבלות\n"
            "💾 כל התמונות הקשורות הוסרו מהאחסון"
        )

        logger.info(f"Deleted {deleted_count} receipts")

    else:
        message = "❌ לא נמצאו קבלות למחיקה. אין קבלות שמורות כרגע."
        logger.info("No receipts found to delete")

    telegram_service.send_message(chat_id, message)
    return create_response(200, {"status": "delete_all_command_handled"})
