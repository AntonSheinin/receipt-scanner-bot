"""
    Telegram Service module using pyTelegramBotAPI
"""

import json
import logging
from typing import Optional, List, Dict, Any
import telebot
from config import BOT_TOKEN, MAX_MESSAGE_LENGTH, setup_logging


setup_logging()
logger = logging.getLogger(__name__)

class TelegramService:
    """Telegram service using pyTelegramBotAPI"""

    def __init__(self):
        if not BOT_TOKEN or BOT_TOKEN == "placeholder_token_for_bootstrap":
            logger.error("Invalid bot token")
            raise ValueError("Bot token is required")

        self.bot = telebot.TeleBot(BOT_TOKEN)
        # Configure timeouts for Lambda environment
        telebot.apihelper.CONNECT_TIMEOUT = 30
        telebot.apihelper.READ_TIMEOUT = 30

    def send_message(self, chat_id: int, text: str, parse_mode: str = "Markdown") -> bool:
        """Send message with automatic fallback"""
        try:
            if len(text) > MAX_MESSAGE_LENGTH:
                text = text[:MAX_MESSAGE_LENGTH-100] + "\n\n... _(Message truncated due to length limit)_"

            # Clean text for Telegram markdown if needed
            if parse_mode == "Markdown":
                text = self._clean_markdown(text)

            self.bot.send_message(chat_id, text, parse_mode=parse_mode)
            return True

        except telebot.apihelper.ApiTelegramException as e:
            if "can't parse entities" in str(e).lower():
                logger.warning("Markdown parsing failed, sending as plain text")
                try:
                    self.bot.send_message(chat_id, text, parse_mode=None)
                    return True
                except Exception as fallback_error:
                    logger.error(f"Fallback message failed: {fallback_error}")
                    self._send_fallback_message(chat_id)
                    return False
            else:
                logger.error(f"Telegram API error: {e}")
                self._send_fallback_message(chat_id)
                return False
        except Exception as e:
            logger.error(f"Unexpected send message error: {e}")
            self._send_fallback_message(chat_id)
            return False

    def send_typing(self, chat_id: int) -> bool:
        """Send typing indicator"""
        try:
            self.bot.send_chat_action(chat_id, 'typing')
            return True
        except Exception as e:
            logger.warning(f"Send typing error: {e}")
            return False

    def download_photo(self, photos: List[Dict]) -> Optional[bytes]:
        """Download the largest photo from Telegram"""
        try:
            if not photos:
                logger.error("No photos provided")
                return None

            # Get largest photo
            largest = max(photos, key=lambda x: x.get('file_size', 0))

            # Download using telebot
            file_info = self.bot.get_file(largest['file_id'])
            downloaded_file = self.bot.download_file(file_info.file_path)

            logger.info(f"Downloaded photo: {len(downloaded_file)} bytes")
            return downloaded_file

        except Exception as e:
            logger.error(f"Photo download error: {e}")
            return None

    def send_error(self, chat_id: int, message: str) -> Dict:
        """Send error message and return response"""
        self.send_message(chat_id, f"❌ {message}")
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"status": "error"})
        }

    # Webhook Management Methods
    def set_webhook(self, webhook_url: str) -> Dict[str, Any]:
        """Set Telegram webhook URL"""
        try:
            logger.info(f"Setting webhook to: {webhook_url}")

            result = self.bot.set_webhook(
                url=webhook_url,
                max_connections=40,
                allowed_updates=['message', 'callback_query'],
                drop_pending_updates=True
            )

            if result:
                # Verify webhook was set
                webhook_info = self.bot.get_webhook_info()
                if webhook_info.url != webhook_url:
                    raise Exception(f"Webhook verification failed. Expected: {webhook_url}, Got: {webhook_info.url}")

                logger.info("✅ Webhook set and verified successfully")
                return {'success': True, 'message': 'Webhook set and verified'}
            else:
                raise Exception("Webhook setup returned False")

        except Exception as e:
            logger.error(f"FAILED to set webhook: {e}")
            raise Exception(f"Webhook setup failed: {str(e)}")

    def delete_webhook(self) -> Dict[str, Any]:
        """Delete Telegram webhook"""
        try:
            logger.info("Deleting webhook...")

            result = self.bot.delete_webhook()
            if result:
                logger.info("✅ Webhook deleted successfully")
                return {'success': True, 'message': 'Webhook deleted successfully'}
            else:
                raise Exception("Webhook deletion returned False")

        except Exception as e:
            logger.error(f"Error deleting webhook: {e}")
            raise

    def get_webhook_info(self) -> Dict[str, Any]:
        """Get current webhook information"""
        try:
            webhook_info = self.bot.get_webhook_info()
            return {
                'url': webhook_info.url,
                'has_custom_certificate': webhook_info.has_custom_certificate,
                'pending_update_count': webhook_info.pending_update_count,
                'last_error_date': webhook_info.last_error_date,
                'last_error_message': webhook_info.last_error_message,
                'max_connections': webhook_info.max_connections,
                'allowed_updates': webhook_info.allowed_updates
            }
        except Exception as e:
            logger.error(f"Error getting webhook info: {e}")
            return {}

    def set_bot_commands(self) -> Dict[str, Any]:
        """Set bot commands for Telegram UI"""
        try:
            commands = [
                telebot.types.BotCommand("start", "Start the bot and show welcome message"),
                telebot.types.BotCommand("help", "Show help information"),
                telebot.types.BotCommand("delete_last", "Delete your most recent receipt"),
                telebot.types.BotCommand("delete_all", "Delete all your receipts"),
            ]

            logger.info(f"Setting {len(commands)} bot commands")

            result = self.bot.set_my_commands(commands)
            if result:
                logger.info("✅ Bot commands set successfully")
                return {'success': True, 'message': 'Bot commands set successfully'}
            else:
                raise Exception("Commands setup returned False")

        except Exception as e:
            logger.error(f"FAILED to set bot commands: {e}")
            raise Exception(f"Command setup failed: {str(e)}")

    # Helper Methods
    def _clean_markdown(self, text: str) -> str:
        """Clean text for Telegram markdown"""
        # Escape problematic characters but preserve intentional formatting
        text = text.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
        # Restore intentional bold formatting
        text = text.replace('\\*\\*', '**')
        # Restore intentional italic formatting
        text = text.replace('\\_\\_', '__')
        return text

    def _send_fallback_message(self, chat_id: int) -> None:
        """Send simple fallback message when main message fails"""
        try:
            fallback_text = "✅ Request processed successfully, but response formatting failed."
            self.bot.send_message(chat_id, fallback_text, parse_mode=None)
        except Exception as e:
            logger.error(f"Even fallback message failed: {e}")
