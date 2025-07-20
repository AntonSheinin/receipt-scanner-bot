"""
Telegram Lambda Handler for Receipt Recognition
"""
import json
import logging
import os
import base64
from typing import Dict, Any, Optional
import boto3
import requests
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize AWS clients
bedrock_client = boto3.client('bedrock-runtime', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Telegram configuration
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
BEDROCK_MODEL_ID = os.environ.get('BEDROCK_MODEL_ID', 'anthropic.claude-3-5-sonnet-20241022-v2:0')

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main Lambda handler for Telegram webhook"""
    try:
        logger.info(f"Received event: {json.dumps(event, default=str)}")
        
        # Parse Telegram update
        body = json.loads(event.get('body', '{}'))
        
        if 'message' not in body:
            return create_response(200, {"status": "no message"})
        
        message = body['message']
        chat_id = message['chat']['id']
        
        # Handle photo messages
        if 'photo' in message:
            return handle_photo_message(message, chat_id)
        
        # Handle text messages
        elif 'text' in message:
            return handle_text_message(message, chat_id)
        
        return create_response(200, {"status": "message type not supported"})
        
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        return create_response(500, {"error": str(e)})


def handle_photo_message(message: Dict[str, Any], chat_id: int) -> Dict[str, Any]:
    """Process receipt photo and extract structured data"""
    try:
        # Send typing action
        send_chat_action(chat_id, "typing")
        
        # Get the largest photo
        photos = message['photo']
        largest_photo = max(photos, key=lambda x: x['file_size'])
        
        # Download photo
        photo_data = download_telegram_file(largest_photo['file_id'])
        if not photo_data:
            send_message(chat_id, "❌ Failed to download image. Please try again.")
            return create_response(200, {"status": "download failed"})
        
        # Process with Bedrock
        send_message(chat_id, "🔍 Analyzing receipt... Please wait.")
        
        receipt_data = process_receipt_with_bedrock(photo_data)
        
        if receipt_data:
            # Format and send the result
            formatted_result = format_receipt_result(receipt_data)
            send_message(chat_id, formatted_result)
        else:
            send_message(chat_id, "❌ Could not process receipt. Please ensure the image is clear and contains a valid receipt.")
        
        return create_response(200, {"status": "photo processed"})
        
    except Exception as e:
        logger.error(f"Error handling photo: {str(e)}", exc_info=True)
        send_message(chat_id, "❌ An error occurred while processing your receipt.")
        return create_response(200, {"status": "error"})


def handle_text_message(message: Dict[str, Any], chat_id: int) -> Dict[str, Any]:
    """Handle text messages"""
    text = message.get('text', '').strip()
    
    if text.lower() in ['/start', '/help']:
        welcome_msg = (
            "🧾 *Receipt Recognition Bot*\n\n"
            "Send me a photo of your receipt and I'll extract the structured data!\n\n"
            "I can recognize:\n"
            "• Store name\n"
            "• Date\n"
            "• Receipt number\n"
            "• Items with prices\n"
            "• Total amount\n\n"
            "Just send a clear photo of your receipt! 📸"
        )
        send_message(chat_id, welcome_msg, parse_mode="Markdown")
    else:
        send_message(chat_id, "Please send me a photo of your receipt to analyze! 📸")
    
    return create_response(200, {"status": "text handled"})


def download_telegram_file(file_id: str) -> Optional[bytes]:
    """Download file from Telegram servers"""
    try:
        # Get file info
        response = requests.get(f"{TELEGRAM_API_URL}/getFile", params={"file_id": file_id})
        response.raise_for_status()
        
        file_info = response.json()
        if not file_info.get('ok'):
            logger.error(f"Failed to get file info: {file_info}")
            return None
        
        file_path = file_info['result']['file_path']
        
        # Download file
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        response = requests.get(file_url)
        response.raise_for_status()
        
        return response.content
        
    except Exception as e:
        logger.error(f"Error downloading file: {str(e)}")
        return None


def process_receipt_with_bedrock(image_data: bytes) -> Optional[Dict[str, Any]]:
    """Process receipt image using Bedrock Claude Vision"""
    try:
        # Encode image to base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        # Create the prompt for receipt recognition
        prompt = """Analyze this receipt image and extract the following information in JSON format:

{
    "store_name": "name of the store/business",
    "date": "date in YYYY-MM-DD format",
    "receipt_number": "receipt/transaction number if available",
    "items": [
        {
            "name": "item name",
            "price": "item price as decimal",
            "quantity": "quantity as integer", 
            "category": "food/household/electronics/etc"
        }
    ],
    "total": "total amount as decimal"
}

Important:
- Return ONLY valid JSON, no additional text
- If information is not clearly visible, use null
- For categories, use common categories like: food, beverages, household, electronics, clothing, pharmacy, etc.
- Ensure all prices are decimal numbers
- Be accurate with the data extraction"""

        # Prepare the request body
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        }
        
        # Call Bedrock
        response = bedrock_client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=json.dumps(request_body),
            contentType="application/json"
        )
        
        # Parse response
        response_body = json.loads(response['body'].read())
        
        if 'content' in response_body and response_body['content']:
            content = response_body['content'][0]['text']
            
            # Try to parse as JSON
            try:
                # Clean the response (remove any markdown formatting)
                clean_content = content.strip()
                if clean_content.startswith('```json'):
                    clean_content = clean_content[7:]
                if clean_content.endswith('```'):
                    clean_content = clean_content[:-3]
                clean_content = clean_content.strip()
                
                return json.loads(clean_content)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response: {content}")
                return None
        
        return None
        
    except ClientError as e:
        logger.error(f"Bedrock error: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Error processing with Bedrock: {str(e)}")
        return None


def format_receipt_result(receipt_data: Dict[str, Any]) -> str:
    """Format receipt data for Telegram message"""
    try:
        result = "✅ *Receipt Analysis Complete*\n\n"
        
        # Add store info
        if receipt_data.get('store_name'):
            result += f"🏪 *Store:* {receipt_data['store_name']}\n"
        
        if receipt_data.get('date'):
            result += f"📅 *Date:* {receipt_data['date']}\n"
        
        if receipt_data.get('receipt_number'):
            result += f"🧾 *Receipt #:* {receipt_data['receipt_number']}\n"
        
        result += "\n"
        
        # Add items
        items = receipt_data.get('items', [])
        if items:
            result += "*📋 Items:*\n"
            for item in items:
                name = item.get('name', 'Unknown item')
                price = item.get('price', 0)
                quantity = item.get('quantity', 1)
                category = item.get('category', '')
                
                line = f"• {name}"
                if quantity > 1:
                    line += f" (x{quantity})"
                line += f" - ${price}"
                if category:
                    line += f" `[{category}]`"
                result += line + "\n"
        
        # Add total
        if receipt_data.get('total'):
            result += f"\n💰 *Total:* ${receipt_data['total']}"
        
        # Add raw JSON
        result += f"\n\n*Raw JSON:*\n```json\n{json.dumps(receipt_data, indent=2)}\n```"
        
        return result
        
    except Exception as e:
        logger.error(f"Error formatting result: {str(e)}")
        return f"✅ Receipt processed successfully!\n\n```json\n{json.dumps(receipt_data, indent=2)}\n```"


def send_message(chat_id: int, text: str, parse_mode: str = "Markdown") -> bool:
    """Send message to Telegram chat"""
    try:
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        response = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=data)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")
        return False


def send_chat_action(chat_id: int, action: str) -> bool:
    """Send chat action (typing, uploading_photo, etc.)"""
    try:
        data = {
            "chat_id": chat_id,
            "action": action
        }
        response = requests.post(f"{TELEGRAM_API_URL}/sendChatAction", json=data)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Error sending chat action: {str(e)}")
        return False


def create_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Create Lambda response"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(body)
    }