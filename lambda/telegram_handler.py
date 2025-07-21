"""
Telegram Lambda Handler for Receipt Recognition with S3, DynamoDB storage and Query System
"""
import json
import logging
import os
import base64
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import boto3
import requests
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize AWS clients
bedrock_client = boto3.client('bedrock-runtime', region_name=os.environ.get('BEDROCK_REGION', 'eu-west-1'))
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

# Environment variables
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
BEDROCK_MODEL_ID = os.environ.get('BEDROCK_MODEL_ID', 'eu.anthropic.claude-3-5-sonnet-20240620-v1:0')
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME')

# DynamoDB table
receipts_table = dynamodb.Table(DYNAMODB_TABLE_NAME) if DYNAMODB_TABLE_NAME else None

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
        
        # Generate unique receipt ID
        receipt_id = str(uuid.uuid4())
        user_id = str(chat_id)
        
        # Store image in S3
        send_message(chat_id, "📁 Storing image...")
        image_url = store_image_in_s3(receipt_id, photo_data)
        if not image_url:
            send_message(chat_id, "❌ Failed to store image. Please try again.")
            return create_response(200, {"status": "storage failed"})
        
        # Process with Bedrock
        send_message(chat_id, "🔍 Analyzing receipt... Please wait.")
        
        receipt_data = process_receipt_with_bedrock(photo_data)
        
        if receipt_data:
            # Store receipt data in DynamoDB
            store_receipt_in_dynamodb(receipt_id, user_id, receipt_data, image_url)
            
            # Format and send the result
            formatted_result = format_receipt_result(receipt_data, receipt_id)
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
            "💾 Your receipts are automatically stored and you'll get a unique ID for each one.\n\n"
            "📊 *Ask me questions like:*\n"
            "• \"How much did I spend on food in August?\"\n"
            "• \"Which store has the cheapest milk?\"\n"
            "• \"Show me all receipts from Rami Levy\"\n"
            "• \"How many times did I shop last month?\"\n\n"
            "Just send a clear photo of your receipt! 📸"
        )
        send_message(chat_id, welcome_msg, parse_mode="Markdown")
    else:
        # Process as query about stored receipts
        return handle_receipt_query(text, str(chat_id))
    
    return create_response(200, {"status": "text handled"})


def handle_receipt_query(user_question: str, user_id: str) -> Dict[str, Any]:
    """Handle natural language queries about stored receipts - 4-step process"""
    try:
        chat_id = int(user_id)
        
        # Send processing message
        send_chat_action(chat_id, "typing")
        send_message(chat_id, "🔍 Analyzing your question... Please wait.")
        
        # Step 1: Generate query plan using LLM
        query_plan = generate_query_plan(user_question)
        if not query_plan:
            send_message(chat_id, "❌ I couldn't understand your question. Please try asking about your receipts in a different way.")
            return create_response(200, {"status": "query_plan_failed"})
        
        logger.info(f"Generated query plan: {query_plan}")
        
        # Step 2: Execute DynamoDB query and aggregate results
        aggregated_data = execute_and_aggregate(query_plan, user_id)
        if not aggregated_data:
            send_message(chat_id, "❌ No data found matching your query. Make sure you have receipts stored first!")
            return create_response(200, {"status": "no_data_found"})
        
        logger.info(f"Aggregated results: {aggregated_data['results']}")
        
        # Step 3: Generate human-readable response using LLM
        send_message(chat_id, "💭 Generating your answer...")
        human_response = generate_human_response(user_question, aggregated_data)
        
        if human_response:
            # Step 4: Send formatted response to user
            send_message(chat_id, human_response, parse_mode="Markdown")
        else:
            send_message(chat_id, "❌ I had trouble generating a response. Please try rephrasing your question.")
        
        return create_response(200, {"status": "query_processed"})
        
    except Exception as e:
        logger.error(f"Error handling receipt query: {str(e)}", exc_info=True)
        send_message(int(user_id), "❌ An error occurred while processing your question. Please try again.")
        return create_response(200, {"status": "error"})


def store_image_in_s3(receipt_id: str, image_data: bytes) -> Optional[str]:
    """Store receipt image in S3 and return the URL"""
    try:
        if not S3_BUCKET_NAME:
            logger.error("S3 bucket name not configured")
            return None
            
        # Create S3 key with timestamp and receipt ID
        timestamp = datetime.utcnow().strftime('%Y/%m/%d')
        s3_key = f"receipts/{timestamp}/{receipt_id}.jpg"
        
        # Upload to S3
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            Body=image_data,
            ContentType='image/jpeg',
            Metadata={
                'receipt_id': receipt_id,
                'uploaded_at': datetime.utcnow().isoformat()
            }
        )
        
        # Return S3 URL
        s3_url = f"s3://{S3_BUCKET_NAME}/{s3_key}"
        logger.info(f"Image stored in S3: {s3_url}")
        return s3_url
        
    except ClientError as e:
        logger.error(f"Error storing image in S3: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error storing image: {str(e)}")
        return None


def store_receipt_in_dynamodb(receipt_id: str, user_id: str, receipt_data: Dict[str, Any], image_url: str) -> bool:
    """Store receipt data in DynamoDB"""
    try:
        if not receipts_table:
            logger.error("DynamoDB table not configured")
            return False
            
        # Prepare item for DynamoDB
        item = {
            'receipt_id': receipt_id,
            'user_id': user_id,
            'created_at': datetime.utcnow().isoformat(),
            'image_url': image_url,
            'store_name': receipt_data.get('store_name'),
            'date': receipt_data.get('date'),
            'receipt_number': receipt_data.get('receipt_number'),
            'total': receipt_data.get('total'),
            'items': receipt_data.get('items', []),
            'raw_data': receipt_data  # Store complete recognition result
        }
        
        # Remove None values
        item = {k: v for k, v in item.items() if v is not None}
        
        # Store in DynamoDB
        receipts_table.put_item(Item=item)
        
        logger.info(f"Receipt stored in DynamoDB: {receipt_id}")
        return True
        
    except ClientError as e:
        logger.error(f"Error storing receipt in DynamoDB: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error storing receipt: {str(e)}")
        return False


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
        
        # Create the prompt for receipt recognition with internal reasoning
        prompt = """Analyze this receipt image carefully and extract structured data. Think through the analysis step-by-step internally:

- First examine the overall layout and identify languages used
- Locate and read all text sections methodically 
- Identify item names, prices, quantities, and categories
- Validate that extracted prices are reasonable and properly formatted
- Cross-reference individual items with the total amount
- Preserve Hebrew/non-Latin text properly without escaping to Unicode

Extract the following information in valid JSON format ONLY (no additional text or explanations):

{
    "store_name": "name of the store/business",
    "date": "date in YYYY-MM-DD format",
    "receipt_number": "receipt/transaction number if available",
    "items": [
        {
            "name": "item name (preserve Hebrew characters properly)",
            "price": "item price as decimal number",
            "quantity": "quantity as integer", 
            "category": "food/beverages/household/electronics/clothing/pharmacy/etc"
        }
    ],
    "total": "total amount as decimal number"
}

Important:
- Return ONLY the JSON object, no markdown formatting or explanations
- If information is not clearly visible, use null
- Ensure all prices are valid decimal numbers
- Preserve Hebrew and special characters correctly
- Categorize items accurately based on context and name
- Validate that individual item prices logically add up to the total"""

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


def generate_query_plan(user_question: str) -> Optional[Dict[str, Any]]:
    """Step 1: Generate DynamoDB query plan using LLM"""
    try:
        # Get current date for relative date parsing
        current_date = datetime.utcnow()
        current_month = current_date.strftime('%Y-%m')
        last_month = (current_date.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
        
        prompt = f"""Analyze this user question about their stored receipts and generate a query plan.

Current date: {current_date.strftime('%Y-%m-%d')}
Current month: {current_month}
Last month: {last_month}

User question: "{user_question}"

Generate a JSON query plan with this structure:
{{
    "filter": {{
        "date_range": {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}},
        "store_names": ["store1", "store2"],
        "item_keywords": ["keyword1", "keyword2"],
        "categories": ["food", "beverages", "household"],
        "price_range": {{"min": 0, "max": 100}}
    }},
    "aggregation": "sum_total|sum_by_category|min_price_by_store|max_price_by_store|count_receipts|list_stores|list_items"
}}

Rules:
- Only include filter fields that are relevant to the question
- For date queries like "August", "last month", "this month", use appropriate date ranges
- For "last month" use: {last_month}-01 to {last_month}-31
- For "this month" use: {current_month}-01 to {current_date.strftime('%Y-%m-%d')}
- For price comparison questions, use min_price_by_store or max_price_by_store
- For spending questions, use sum_total or sum_by_category
- For counting questions, use count_receipts
- Item keywords should include both English and Hebrew terms when possible
- Categories: food, beverages, household, electronics, clothing, pharmacy, health, other

Examples:
"How much did I spend on food in August?" → date_range: August 2025, categories: ["food"], aggregation: "sum_by_category"
"Which store has cheapest milk?" → item_keywords: ["milk", "חלב"], aggregation: "min_price_by_store"
"How many receipts from Rami Levy?" → store_names: ["Rami Levy"], aggregation: "count_receipts"
"How much did I spend last month?" → date_range: last month, aggregation: "sum_total"

Return ONLY the JSON object, no explanations."""

        # Prepare request for Bedrock
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}]
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
            content = response_body['content'][0]['text'].strip()
            
            # Clean JSON response
            if content.startswith('```json'):
                content = content[7:]
            if content.endswith('```'):
                content = content[:-3]
            content = content.strip()
            
            return json.loads(content)
        
        return None
        
    except Exception as e:
        logger.error(f"Error generating query plan: {str(e)}")
        return None


def execute_and_aggregate(query_plan: Dict[str, Any], user_id: str) -> Optional[Dict[str, Any]]:
    """Step 2: Execute DynamoDB query and perform local aggregation"""
    try:
        if not receipts_table:
            logger.error("DynamoDB table not configured")
            return None
        
        # Helper function to convert Decimal to float recursively
        def decimal_to_float(obj):
            from decimal import Decimal
            if isinstance(obj, Decimal):
                return float(obj)
            elif isinstance(obj, dict):
                return {k: decimal_to_float(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [decimal_to_float(v) for v in obj]
            return obj
        
        # Build DynamoDB filter expression
        filter_expressions = ["user_id = :user_id"]
        expression_values = {":user_id": user_id}
        
        filter_params = query_plan.get("filter", {})
        
        # Add date range filter
        if "date_range" in filter_params:
            filter_expressions.append("created_at BETWEEN :start_date AND :end_date")
            expression_values[":start_date"] = filter_params["date_range"]["start"] + "T00:00:00"
            expression_values[":end_date"] = filter_params["date_range"]["end"] + "T23:59:59"
        
        # Add store name filter
        if "store_names" in filter_params and filter_params["store_names"]:
            store_conditions = []
            for i, store in enumerate(filter_params["store_names"]):
                store_conditions.append(f"contains(store_name, :store_{i})")
                expression_values[f":store_{i}"] = store
            filter_expressions.append(f"({' OR '.join(store_conditions)})")
        
        # Execute DynamoDB scan with filters
        scan_params = {
            "FilterExpression": " AND ".join(filter_expressions),
            "ExpressionAttributeValues": expression_values
        }
        
        response = receipts_table.scan(**scan_params)
        receipts = response.get('Items', [])
        
        # Convert all Decimal objects to float
        receipts = decimal_to_float(receipts)
        
        logger.info(f"Found {len(receipts)} receipts from DynamoDB")
        
        # Apply additional filtering that can't be done in DynamoDB
        filtered_receipts = apply_item_level_filtering(receipts, filter_params)
        
        logger.info(f"After item-level filtering: {len(filtered_receipts)} receipts")
        
        # Apply aggregation
        aggregation_type = query_plan.get("aggregation", "count_receipts")
        results = apply_aggregation(filtered_receipts, filter_params, aggregation_type)
        
        return {
            "query": query_plan,
            "results": results,
            "raw_data": filtered_receipts[:3],  # Sample for context
            "total_receipts": len(filtered_receipts)
        }
        
    except Exception as e:
        logger.error(f"Error executing query: {str(e)}")
        return None


def apply_item_level_filtering(receipts: List[Dict], filter_params: Dict) -> List[Dict]:
    """Apply filtering that requires looking at individual items within receipts"""
    try:
        filtered_receipts = []
        
        categories = filter_params.get("categories", [])
        item_keywords = filter_params.get("item_keywords", [])
        price_range = filter_params.get("price_range", {})
        
        for receipt in receipts:
            receipt_matches = False
            items = receipt.get('items', [])
            
            # If no item-level filters, include the receipt
            if not categories and not item_keywords and not price_range:
                filtered_receipts.append(receipt)
                continue
            
            # Check if receipt has items matching the criteria
            for item in items:
                item_matches = True
                
                # Check category filter
                if categories:
                    item_category = item.get('category', '').lower()
                    if not any(cat.lower() in item_category or item_category == cat.lower() for cat in categories):
                        item_matches = False
                
                # Check keyword filter
                if item_keywords and item_matches:
                    item_name = item.get('name', '').lower()
                    if not any(keyword.lower() in item_name for keyword in item_keywords):
                        item_matches = False
                
                # Check price range filter
                if price_range and item_matches:
                    item_price = float(item.get('price', 0))
                    min_price = price_range.get('min', 0)
                    max_price = price_range.get('max', float('inf'))
                    if not (min_price <= item_price <= max_price):
                        item_matches = False
                
                # If this item matches all criteria, include the receipt
                if item_matches:
                    receipt_matches = True
                    break
            
            if receipt_matches:
                filtered_receipts.append(receipt)
        
        return filtered_receipts
        
    except Exception as e:
        logger.error(f"Error in item-level filtering: {str(e)}")
        return receipts  # Return original receipts if filtering fails


def apply_aggregation(receipts: List[Dict], filter_params: Dict, aggregation_type: str) -> Dict[str, Any]:
    """Apply local aggregation to filtered receipts"""
    try:
        # Helper function to convert Decimal to float
        def decimal_to_float(obj):
            from decimal import Decimal
            if isinstance(obj, Decimal):
                return float(obj)
            elif isinstance(obj, dict):
                return {k: decimal_to_float(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [decimal_to_float(v) for v in obj]
            return obj
        
        # Convert all receipts to handle Decimal objects
        receipts = decimal_to_float(receipts)
        
        if aggregation_type == "count_receipts":
            return {
                "count": len(receipts),
                "type": "count"
            }
        
        elif aggregation_type == "sum_total":
            total = sum(float(receipt.get('total', 0)) for receipt in receipts if receipt.get('total'))
            return {
                "total_spent": round(total, 2),
                "receipt_count": len(receipts),
                "type": "sum_total"
            }
        
        elif aggregation_type == "sum_by_category":
            category_sums = {}
            categories = filter_params.get("categories", [])
            
            for receipt in receipts:
                for item in receipt.get('items', []):
                    item_category = item.get('category', 'other')
                    
                    # If categories filter is specified, only include matching items
                    if categories:
                        if not any(cat.lower() in item_category.lower() or item_category.lower() == cat.lower() for cat in categories):
                            continue
                    
                    price = float(item.get('price', 0)) * int(item.get('quantity', 1))
                    category_sums[item_category] = category_sums.get(item_category, 0) + price
            
            # Round all values
            category_sums = {k: round(v, 2) for k, v in category_sums.items()}
            
            return {
                "category_totals": category_sums,
                "total_spent": round(sum(category_sums.values()), 2),
                "receipt_count": len(receipts),
                "type": "category_breakdown"
            }
        
        elif aggregation_type in ["min_price_by_store", "max_price_by_store"]:
            keywords = filter_params.get("item_keywords", [])
            categories = filter_params.get("categories", [])
            store_prices = {}
            
            for receipt in receipts:
                store = receipt.get('store_name', 'Unknown Store')
                for item in receipt.get('items', []):
                    item_name = item.get('name', '').lower()
                    item_category = item.get('category', '').lower()
                    
                    item_matches = True
                    
                    # Check keyword filter
                    if keywords:
                        if not any(keyword.lower() in item_name for keyword in keywords):
                            item_matches = False
                    
                    # Check category filter
                    if categories and item_matches:
                        if not any(cat.lower() in item_category or item_category == cat.lower() for cat in categories):
                            item_matches = False
                    
                    # If item matches criteria, consider for price comparison
                    if item_matches:
                        price = float(item.get('price', 0))
                        if price > 0:
                            if store not in store_prices:
                                store_prices[store] = price
                            elif aggregation_type == "min_price_by_store":
                                store_prices[store] = min(store_prices[store], price)
                            else:  # max_price_by_store
                                store_prices[store] = max(store_prices[store], price)
            
            # Round all values
            store_prices = {k: round(v, 2) for k, v in store_prices.items()}
            
            return {
                "store_prices": store_prices,
                "keywords": keywords,
                "categories": categories,
                "type": "price_comparison",
                "comparison_type": "min" if aggregation_type == "min_price_by_store" else "max"
            }
        
        elif aggregation_type == "list_stores":
            stores = list(set(receipt.get('store_name', 'Unknown') for receipt in receipts))
            return {
                "stores": stores,
                "store_count": len(stores),
                "receipt_count": len(receipts),
                "type": "store_list"
            }
        
        else:
            # Default fallback
            return {
                "receipt_count": len(receipts),
                "type": "default"
            }
    
    except Exception as e:
        logger.error(f"Error in aggregation: {str(e)}")
        return {"error": str(e), "type": "error"}


def generate_human_response(user_question: str, aggregated_data: Dict[str, Any]) -> Optional[str]:
    """Step 3: Generate human-readable response using LLM"""
    try:
        results = aggregated_data.get("results", {})
        query = aggregated_data.get("query", {})
        
        prompt = f"""The user asked: "{user_question}"

Query executed: {json.dumps(query, indent=2)}

Aggregation results: {json.dumps(results, indent=2)}

Total receipts found: {aggregated_data.get('total_receipts', 0)}

Sample receipt data for context: {json.dumps(aggregated_data.get('raw_data', []), indent=2)}

Generate a helpful, conversational response for Telegram. Requirements:
1. Answer the user's question directly and clearly
2. Include relevant numbers and insights
3. Use emojis and markdown formatting for Telegram
4. Be conversational and helpful, not robotic
5. If no results found, explain why and suggest alternatives
6. For price comparisons, highlight the best deal
7. For spending analysis, provide useful insights

Format for Telegram with **bold** text and emojis. Keep it concise but informative."""

        # Prepare request for Bedrock
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1500,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}]
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
            return response_body['content'][0]['text'].strip()
        
        return None
        
    except Exception as e:
        logger.error(f"Error generating human response: {str(e)}")
        return None


def format_receipt_result(receipt_data: Dict[str, Any], receipt_id: str) -> str:
    """Format receipt data for Telegram message"""
    try:
        result = "✅ *Receipt Analysis Complete*\n\n"
        
        # Add store info
        if receipt_data.get('store_name'):
            store_name = receipt_data['store_name']
            # Ensure proper Unicode handling for Hebrew/non-Latin text
            if isinstance(store_name, str):
                store_name = store_name.encode('utf-8').decode('utf-8')
            result += f"🏪 *Store:* {store_name}\n"
        
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
                # Ensure proper Unicode handling for item names
                if isinstance(name, str):
                    name = name.encode('utf-8').decode('utf-8')
                    
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
        
        # Add receipt ID for reference
        result += f"\n\n🆔 *Receipt ID:* `{receipt_id}`"
        result += f"\n✅ *Stored successfully in database*"
        
        # Add raw JSON with proper Unicode handling
        result += f"\n\n*Raw JSON:*\n```json\n{json.dumps(receipt_data, indent=2, ensure_ascii=False)}\n```"
        
        return result
        
    except Exception as e:
        logger.error(f"Error formatting result: {str(e)}")
        # Fallback with proper Unicode
        return f"✅ Receipt processed successfully!\n\n🆔 *Receipt ID:* `{receipt_id}`\n✅ *Stored in database*\n\n```json\n{json.dumps(receipt_data, indent=2, ensure_ascii=False)}\n```"


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