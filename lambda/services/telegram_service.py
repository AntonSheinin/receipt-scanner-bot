"""
Telegram API Service
"""
import json
import logging
from typing import Optional, List, Dict
import requests

from config import TELEGRAM_API_URL, MAX_MESSAGE_LENGTH, BOT_TOKEN

logger = logging.getLogger(__name__)


class TelegramService:
    """Service for Telegram API interactions"""
    
    def send_message(self, chat_id: int, text: str, parse_mode: str = "Markdown") -> bool:
        """Send message to Telegram chat with error handling"""
        try:
            if len(text) > MAX_MESSAGE_LENGTH:
                text = text[:MAX_MESSAGE_LENGTH-100] + "\n\n... _(Message truncated due to length limit)_"
            
            # Clean text for Telegram markdown
            text = self._clean_markdown(text)
            
            data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
            response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=data)
            
            # Retry without markdown if parsing fails
            if response.status_code == 400:
                logger.warning("Markdown parsing failed, sending as plain text")
                data["parse_mode"] = None
                response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=data)
            
            response.raise_for_status()
            return True
            
        except Exception as e:
            logger.error(f"Send message error: {e}")
            self._send_fallback_message(chat_id)
            return False
    
    def send_typing(self, chat_id: int):
        """Send typing indicator"""
        try:
            requests.post(f"{TELEGRAM_API_URL}/sendChatAction", 
                         json={"chat_id": chat_id, "action": "typing"})
        except:
            pass
    
    def download_photo(self, photos: List[Dict]) -> Optional[bytes]:
        """Download the largest photo from Telegram"""
        try:
            largest = max(photos, key=lambda x: x['file_size'])
            
            # Get file info
            file_response = requests.get(f"{TELEGRAM_API_URL}/getFile", 
                                       params={"file_id": largest['file_id']})
            file_response.raise_for_status()
            file_info = file_response.json()
            
            if not file_info.get('ok'):
                logger.error(f"Failed to get file info: {file_info}")
                return None
            
            # Download file - Fixed URL construction
            file_path = file_info['result']['file_path']
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
            file_response = requests.get(file_url)
            file_response.raise_for_status()
            
            return file_response.content
            
        except Exception as e:
            logger.error(f"Photo download error: {e}")
            return None
    
    def send_error(self, chat_id: int, message: str) -> Dict:
        """Send error message and return response"""
        self.send_message(chat_id, f"❌ {message}")
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"status": "error"})}
    
    def _clean_markdown(self, text: str) -> str:
        """Clean text for Telegram markdown"""
        text = text.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')
        text = text.replace('\\*\\*', '**').replace('\\_', '_')
        return text
    
    def _send_fallback_message(self, chat_id: int):
        """Send simple fallback message"""
        try:
            simple_data = {
                "chat_id": chat_id,
                "text": "✅ Query processed successfully, but response was too long to display.",
                "parse_mode": None
            }
            requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=simple_data)
        except:
            pass