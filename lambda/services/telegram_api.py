"""
Telegram API Service for Webhook Management
"""
import json
import urllib3
from typing import Dict, Any

class TelegramAPI:
    """Service for Telegram API interactions"""
    
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.http = urllib3.PoolManager()
    
    def set_webhook(self, webhook_url: str) -> Dict[str, Any]:
        """Set Telegram webhook URL"""
        try:
            print(f"Setting webhook to: {webhook_url}")
            
            webhook_data = {
                'url': webhook_url,
                'max_connections': 40,
                'allowed_updates': ['message', 'callback_query'],
                'drop_pending_updates': True  # Clear any pending updates
            }
            
            response = self.http.request(
                'POST',
                f"{self.base_url}/setWebhook",
                body=json.dumps(webhook_data),
                headers={'Content-Type': 'application/json'},
                timeout=30.0
            )
            
            if response.status != 200:
                raise Exception(f"HTTP {response.status}: {response.data.decode('utf-8')}")
            
            result = json.loads(response.data.decode('utf-8'))
            print(f"Webhook result: {result}")
            
            if not result.get('ok'):
                raise Exception(f"Webhook setup failed: {result.get('description', 'Unknown error')}")
            
            # Verify webhook was set
            verification = self.get_webhook_info()
            expected_url = webhook_url
            actual_url = verification.get('url', '')
            
            if actual_url != expected_url:
                raise Exception(f"Webhook verification failed. Expected: {expected_url}, Got: {actual_url}")
            
            print("✅ Webhook set and verified successfully")
            return {'success': True, 'message': 'Webhook set and verified'}
            
        except Exception as e:
            print(f"FAILED to set webhook: {e}")
            raise Exception(f"Webhook setup failed: {str(e)}")
    
    def delete_webhook(self) -> Dict[str, Any]:
        """Delete Telegram webhook"""
        try:
            print("Deleting webhook...")
            
            response = self.http.request(
                'POST',
                f"{self.base_url}/deleteWebhook"
            )
            
            result = json.loads(response.data.decode('utf-8'))
            print(f"Delete webhook result: {result}")
            
            if result.get('ok'):
                return {'success': True, 'message': 'Webhook deleted successfully'}
            else:
                raise Exception(f"Failed to delete webhook: {result.get('description', 'Unknown error')}")
                
        except Exception as e:
            print(f"Error deleting webhook: {e}")
            raise
    
    def get_webhook_info(self) -> Dict[str, Any]:
        """Get current webhook information"""
        try:
            response = self.http.request(
                'GET',
                f"{self.base_url}/getWebhookInfo"
            )
            
            result = json.loads(response.data.decode('utf-8'))
            
            if result.get('ok'):
                return result.get('result', {})
            else:
                raise Exception(f"Failed to get webhook info: {result.get('description', 'Unknown error')}")
                
        except Exception as e:
            print(f"Error getting webhook info: {e}")
            return {}
    
    def set_bot_commands(self) -> Dict[str, Any]:
        """Set bot commands for Telegram UI"""
        try:
            commands = [
                {"command": "start", "description": "Start the bot and show welcome message"},
                {"command": "help", "description": "Show help information"},
                {"command": "delete_last", "description": "Delete your most recent receipt"},
                {"command": "delete_all", "description": "Delete all your receipts"},
            ]
            
            print(f"Setting {len(commands)} bot commands")
            
            response = self.http.request(
                'POST',
                f"{self.base_url}/setMyCommands",
                body=json.dumps({"commands": commands}),
                headers={'Content-Type': 'application/json'},
                timeout=30.0  # Add timeout
            )
            
            if response.status != 200:
                raise Exception(f"HTTP {response.status}: {response.data.decode('utf-8')}")
            
            result = json.loads(response.data.decode('utf-8'))
            print(f"Telegram API response: {result}")
            
            if not result.get('ok'):
                raise Exception(f"Telegram API error: {result.get('description', 'Unknown error')}")
            
            print("✅ Bot commands set successfully")
            return {'success': True, 'message': 'Bot commands set successfully'}
                
        except Exception as e:
            print(f"FAILED to set bot commands: {e}")
            raise Exception(f"Command setup failed: {str(e)}")