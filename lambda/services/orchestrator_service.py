"""
    Orchestration Service module
"""

import logging
import os
import tempfile
from typing import Dict, Any
from enum import Enum
from services.receipt_service import ReceiptService
from services.query_service import QueryService
from services.telegram_service import TelegramService
from services.storage_service import StorageService
from config import MAX_RECEIPTS_PER_USER, setup_logging
from providers.helpers import get_secure_user_id
from providers.image_preprocessor.pillow_preprocessor import ImageStitchingAndPreprocessing


setup_logging()
logger = logging.getLogger(__name__)

class MessageType(Enum):
    """Telegram message types"""
    PHOTO = "photo"
    TEXT_QUERY = "text"
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

    def process_telegram_album(self, album_messages: list):
        """
            Combine all images in a Telegram album, preprocess them, and call process_telegram_message.
        """
        if not album_messages:
            logger.warning("Empty album received, skipping processing")
            return None

        chat_id = album_messages[0]['chat_id']
        logger.info(f"Processing album with {len(album_messages)} images for chat_id {chat_id}")

        # Use a single temporary directory for all downloaded images
        with tempfile.TemporaryDirectory() as tmp_dir:
            img_paths = []

            try:
                # Download images to temp dir
                for msg in album_messages:
                    if "photo" not in msg:
                        continue
                    photo_sizes = msg["photo"]
                    file_id = photo_sizes[-1]["file_id"]
                    local_path = self.telegram_service.download_file(file_id, download_dir=tmp_dir)
                    img_paths.append(local_path)

                if not img_paths:
                    logger.warning("No images found in album messages")
                    return None

                # Stitch, deskew, and preprocess in memory
                stitched_img = ImageStitchingAndPreprocessing.stitch_receipts(img_paths)
                deskewed_img = ImageStitchingAndPreprocessing.deskew_image(stitched_img)
                preprocessed_img = ImageStitchingAndPreprocessing.preprocess_for_ocr(deskewed_img)

                # Save preprocessed image to a temporary file and call the existing message processor
                with tempfile.NamedTemporaryFile(suffix=".png") as tmp_file:
                    preprocessed_img.save(tmp_file.name)
                    combined_message = {
                        "chat_id": chat_id,
                        "photo": [{"file_path": tmp_file.name}]
                    }

                    self.telegram_service.send_photo(chat_id, tmp_file.name, caption="📸 Combined & preprocessed photo")
                    # return self.process_telegram_message(combined_message)

            except Exception as e:
                logger.error(f"Failed to process telegram album: {e}", exc_info=True)
                return None

    def process_telegram_message(self, telegram_message: Dict[str, Any]) -> Dict[str, Any]:
        """Main orchestration method - routes message to appropriate service"""

        chat_id = telegram_message['chat_id']
        message_type = telegram_message['message_type']

        logger.info(f"Orchestrating {message_type} message for chat_id: {chat_id}")

        try:
            if message_type == MessageType.PHOTO.value:
                return self._handle_photo_message(telegram_message, chat_id)

            if message_type == MessageType.TEXT_QUERY.value:
                return self._handle_text_query(telegram_message, chat_id)

            if message_type == MessageType.COMMAND.value:
                return self._handle_command_message(telegram_message, chat_id)


            logger.warning(f"Unknown message type for chat_id: {chat_id}")
            self.telegram_service.send_message(chat_id, "❓ לא הבנתי את סוג ההודעה. אנא שלח תמונה של קבלה או שאל שאלה.")
            return {"status": "unknown_message_type"}

        except Exception as e:
            logger.error(f"Orchestration error for chat_id {chat_id}: {e}", exc_info=True)
            self.telegram_service.send_message(chat_id, "❌ הייתה בעיה בעיבוד ההודעה שלך. אנא נסה שוב.")
            return {"status": "error", "error": str(e)}

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
        self.telegram_service.send_message(chat_id, "📸 מעבד את הקבלה...")

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
        self.telegram_service.send_message(chat_id, "🔍 מעבדים את השאלה...")

        # Process query using query service
        result = self.query_service.process_query(text, chat_id)

        logger.info(f"Query processing completed for chat_id: {chat_id}")
        return {"status": "query_processed", "result": result}

    def _handle_command_message(self, telegram_message: Dict[str, Any], chat_id: int) -> Dict[str, Any]:
        """Handle command messages"""

        text = telegram_message.get('text', '').strip().lower()
        logger.info(f"Processing command for chat_id: {chat_id}, command: '{text}'")

        if text =='/start':
            welcome_message = self._get_welcome_message()
            self.telegram_service.send_message(chat_id, welcome_message)
            return {"status": "welcome_sent"}

        if text == '/help':
            help_message = self._handle_help_command(chat_id)
            self.telegram_service.send_message(chat_id, help_message)
            return {"status": "help_sent"}

        if text == '/delete_last':
            return self._handle_delete_last_command(chat_id)

        if text == '/delete_all':
            return self._handle_delete_all_command(chat_id)

        self.telegram_service.send_message(chat_id, "❓ פקודה לא מזוהה. השתמש ב-/help כדי לראות פקודות זמינות.")
        return {"status": "unknown_command"}

    def _handle_delete_last_command(self, chat_id: int) -> Dict[str, Any]:
        """Handle /delete_last command"""

        self.telegram_service.send_typing(chat_id)
        secure_user_id = get_secure_user_id(chat_id)

        is_deleted = self.storage_service.delete_last_uploaded_receipt(secure_user_id)

        if is_deleted:
            message = "🗑️ הקבלה האחרונה נמחקה בהצלחה\n\n"

            logger.info(f"Deleted last uploaded receipt")
        else:
            message = "❌ לא נמצאו קבלות למחיקה. אין קבלות שמורות כרגע."
            logger.info("No receipts found to delete")

        self.telegram_service.send_message(chat_id, message)
        return {"status": "delete_last_completed"}

    def _handle_delete_all_command(self, chat_id: int) -> Dict[str, Any]:
        """Handle /delete_all command"""

        self.telegram_service.send_typing(chat_id)
        self.telegram_service.send_message(chat_id, "🗑️ מוחק את כל הקבלות... נא להמתין.")

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

    def _get_help_message(self) -> str:
        """Get detailed help message for /help command"""
        return (
            "📖 מדריך שימוש מפורט - בוט סורק קבלות\n\n"
            "📸 איך לצלם קבלה נכון:\n\n"
            "🔧 הגדרות טלגרם:\n"
            "• תשתדלו לצלם ולשלוח תמונת הקבלה באיכות HD ✨\n"
            "• לצורך כך ליחצו על סימן HD בחלק התחתון של התמונה לאחר הצילום\n\n"
            "⚡ מתי לצלם:\n"
            "• מיד לאחר הקנייה בחנות 🏪\n"
            "• לפני שהקבלה מתקמטת או דוהה\n"
            "• כשהתאורה טובה ויש לך זמן לצלם בקפידה\n\n"
            "🎯 טכניקת צילום נכונה:\n"
            "• התקרב מקסימום לקבלה - מלא כל המסך 📏\n"
            "• ודא שהתאריך רואים בבירור בתמונה 📅\n"
            "• תאורה טובה - טבעית או מלאכותית חזקה 💡\n"
            "• הקבלה פרושה ישר - ללא קמטים 📋\n"
            "• המצלמה מקבילה לקבלה (לא באלכסון) 📐\n\n"
            "📏 אם הקבלה ארוכה מדי:\n"
            "• צלם עם המצלמה של הטלפון (לא דרך טלגרם) 📱\n"
            "• צלם 2 תמונות נפרדות עם חפיפה קטנה:\n"
            "  - תמונה 1: החלק העליון + כמה שורות מהאמצע\n"
            "  - תמונה 2: כמה שורות מהאמצע + החלק התחתון\n"
            "• בטלגרם: צרף שתי התמונות מהגלריה בהודעה אחת\n"
            "• (טלגרם מאפשר רק תמונה אחת בצילום ישיר)\n\n"
            f"📊 מגבלה: {MAX_RECEIPTS_PER_USER} קבלות לכל משתמש"
        )
