"""
    Orchestration Service module
"""

import logging
from typing import Dict, Any
from enum import Enum
from services.receipt_service import ReceiptService
from services.query_service import QueryService
from services.telegram_service import TelegramService
from services.storage_service import StorageService
from config import MAX_RECEIPTS_PER_USER, setup_logging
from utils.helpers import get_secure_user_id


setup_logging()
logger = logging.getLogger(__name__)

class MessageType(Enum):
    """Telegram message types"""
    PHOTO = "photo"
    TEXT_QUERY = "text_query"
    COMMAND = "command"
    UNKNOWN = "unknown"

class OrchestratorService:
    """Orchestrates message processing and routing"""

    def __init__(self):
        self.receipt_service = ReceiptService()
        self.query_service = QueryService()
        self.telegram_service = TelegramService()
        self.storage_service = StorageService()

        logger.info("OrchestratorService initialized with all services")

    def process_telegram_message(self, telegram_message: Dict[str, Any]) -> Dict[str, Any]:
        """Main orchestration method - routes message to appropriate service"""

        chat_id = telegram_message['chat']['id']
        message_type = self._determine_message_type(telegram_message)

        logger.info(f"Orchestrating {message_type.value} message for chat_id: {chat_id}")

        try:
            if message_type == MessageType.PHOTO:
                return self._handle_photo_message(telegram_message, chat_id)

            elif message_type == MessageType.TEXT_QUERY:
                return self._handle_text_query(telegram_message, chat_id)

            elif message_type == MessageType.COMMAND:
                return self._handle_command_message(telegram_message, chat_id)

            else:
                logger.warning(f"Unknown message type for chat_id: {chat_id}")
                self.telegram_service.send_message(
                    chat_id,
                    "❓ לא הבנתי את סוג ההודעה. אנא שלח תמונה של קבלה או שאל שאלה."
                )
                return {"status": "unknown_message_type"}

        except Exception as e:
            logger.error(f"Orchestration error for chat_id {chat_id}: {e}", exc_info=True)
            self.telegram_service.send_message(
                chat_id,
                "❌ הייתה בעיה בעיבוד ההודעה שלך. אנא נסה שוב."
            )
            return {"status": "error", "error": str(e)}

    def _determine_message_type(self, telegram_message: Dict[str, Any]) -> MessageType:
        """Determine the type of Telegram message"""

        if 'photo' in telegram_message:
            return MessageType.PHOTO

        elif 'text' in telegram_message:
            text = telegram_message.get('text', '').strip()

            if text.startswith('/'):
                return MessageType.COMMAND

            elif text:
                return MessageType.TEXT_QUERY

        return MessageType.UNKNOWN

    def _handle_photo_message(self, telegram_message: Dict[str, Any], chat_id: int) -> Dict[str, Any]:
        """Handle receipt photo processing"""

        logger.info(f"Processing receipt photo for chat_id: {chat_id}")

        # Check receipt limit before processing
        secure_user_id = get_secure_user_id(chat_id)
        current_count = self.storage_service.count_user_receipts(secure_user_id)

        if current_count >= MAX_RECEIPTS_PER_USER:
            logger.warning(f"User {chat_id} hit receipt limit: {current_count}/{MAX_RECEIPTS_PER_USER}")

            error_message = (
                f"🚫 הגעת למגבלת הקבלות ({MAX_RECEIPTS_PER_USER} קבלות).\n\n"
                f"📊 יש לך כרגע {current_count} קבלות שמורות.\n"
                f"🗑️ השתמש בפקודה /delete_last או /delete_all כדי למחוק קבלות ישנות."
            )

            self.telegram_service.send_message(chat_id, error_message)
            return {"status": "receipt_limit_exceeded"}

        # Send processing message
        self.telegram_service.send_message(chat_id, "📸 מעבדים את הקבלה...")

        # Process receipt using receipt service
        result = self.receipt_service.process_receipt(telegram_message, chat_id)

        logger.info(f"Receipt processing completed for chat_id: {chat_id}")
        return {"status": "receipt_processed", "result": result}

    def _handle_text_query(self, telegram_message: Dict[str, Any], chat_id: int) -> Dict[str, Any]:
        """Handle text query processing"""

        text = telegram_message.get('text', '').strip()
        logger.info(f"Processing text query for chat_id: {chat_id}, query: '{text}'")

        if not text:
            self.telegram_service.send_message(chat_id, "❓ לא קיבלתי שאלה. אנא כתב שאלה על הקבלות שלך.")
            return {"status": "empty_query"}

        # Send processing message
        self.telegram_service.send_message(chat_id, "🔍 מעבדים את השאלה... נא להמתין.")

        # Process query using query service
        result = self.query_service.process_query(text, chat_id)

        logger.info(f"Query processing completed for chat_id: {chat_id}")
        return {"status": "query_processed", "result": result}

    def _handle_command_message(self, telegram_message: Dict[str, Any], chat_id: int) -> Dict[str, Any]:
        """Handle command messages"""

        text = telegram_message.get('text', '').strip().lower()
        logger.info(f"Processing command for chat_id: {chat_id}, command: '{text}'")

        if text in ('/start', '/help'):
            welcome_message = self._get_welcome_message()
            self.telegram_service.send_message(chat_id, welcome_message)
            return {"status": "welcome_sent"}

        elif text == '/delete_last':
            return self._handle_delete_last_command(chat_id)

        elif text == '/delete_all':
            return self._handle_delete_all_command(chat_id)

        else:
            self.telegram_service.send_message(
                chat_id,
                "❓ פקודה לא מזוהה. השתמש ב-/help כדי לראות פקודות זמינות."
            )
            return {"status": "unknown_command"}

    def _handle_delete_last_command(self, chat_id: int) -> Dict[str, Any]:
        """Handle /delete_last command"""

        self.telegram_service.send_typing(chat_id)
        secure_user_id = get_secure_user_id(chat_id)

        deleted_receipt = self.storage_service.delete_last_uploaded_receipt(secure_user_id)

        if deleted_receipt:
            store_name = deleted_receipt.get('store_name', 'Unknown Store')
            receipt_date = deleted_receipt.get('date', 'Unknown Date')
            upload_date = deleted_receipt.get('created_at', 'Unknown Upload Date')
            total = deleted_receipt.get('total', '0.00')

            message = (
                "🗑️ הקבלה האחרונה נמחקה בהצלחה\n\n"
                f"🏪 חנות: {store_name}\n"
                f"📅 תאריך קבלה: {receipt_date}\n"
                f"📤 תאריך העלאה: {upload_date[:10]}\n"
                f"💰 סך הכל: {total} שח\n"
            )

            logger.info(f"Deleted last uploaded receipt {deleted_receipt['receipt_id']}")
        else:
            message = "❌ לא נמצאו קבלות למחיקה. אין קבלות שמורות כרגע."
            logger.info("No receipts found to delete")

        self.telegram_service.send_message(chat_id, message)
        return {"status": "delete_last_completed"}

    def _handle_delete_all_command(self, chat_id: int) -> Dict[str, Any]:
        """Handle /delete_all command"""

        self.telegram_service.send_typing(chat_id)
        self.telegram_service.send_message(chat_id, "🗑️ מוחקים את כל הקבלות... נא להמתין.")

        secure_user_id = get_secure_user_id(chat_id)
        deleted_count = self.storage_service.delete_all_receipts(secure_user_id)

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

        self.telegram_service.send_message(chat_id, message)
        return {"status": "delete_all_completed"}

    def _get_welcome_message(self) -> str:
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
            "💾 הקבלות שלך נשמרות במאגר ללא מידע אישי.\n\n"
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
