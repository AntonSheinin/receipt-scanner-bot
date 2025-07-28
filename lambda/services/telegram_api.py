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
                'allowed_updates': ['message', 'callback_query']
            }
            
            response = self.http.request(
                'POST',
                f"{self.base_url}/setWebhook",
                body=json.dumps(webhook_data),
                headers={'Content-Type': 'application/json'}
            )
            
            result = json.loads(response.data.decode('utf-8'))
            print(f"Set webhook result: {result}")
            
            if result.get('ok'):
                # Verify webhook was set correctly
                verification = self.get_webhook_info()
                if verification.get('url') == webhook_url:
                    print("✅ Webhook verified successfully")
                    return {'success': True, 'message': 'Webhook set and verified'}
                else:
                    raise Exception(f"Webhook verification failed. Expected: {webhook_url}, Got: {verification.get('url')}")
            else:
                raise Exception(f"Failed to set webhook: {result.get('description', 'Unknown error')}")
                
        except Exception as e:
            print(f"Error setting webhook: {e}")
            raise
    
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
            
            print(f"Setting bot commands: {commands}")
            
            response = self.http.request(
                'POST',
                f"{self.base_url}/setMyCommands",
                body=json.dumps({"commands": commands}),
                headers={'Content-Type': 'application/json'}
            )
            
            result = json.loads(response.data.decode('utf-8'))
            print(f"Set commands result: {result}")
            
            if result.get('ok'):
                return {'success': True, 'message': 'Bot commands set successfully'}
            else:
                raise Exception(f"Failed to set commands: {result.get('description', 'Unknown error')}")
                
        except Exception as e:
            print(f"Error setting bot commands: {e}")
            raise