"""
Configuration and Constants
"""
import os
import logging
import boto3

# Environment variables
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
BEDROCK_MODEL_ID = os.environ.get('BEDROCK_MODEL_ID')
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME')
BEDROCK_REGION = os.environ.get('BEDROCK_REGION')

# Telegram API
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Message limits
MAX_MESSAGE_LENGTH = 4000
MAX_ITEMS_DISPLAY = 15
MAX_ITEM_NAME_LENGTH = 30

# AWS Clients (singleton pattern)
_bedrock_client = None
_s3_client = None
_dynamodb = None
_receipts_table = None


def get_bedrock_client():
    """Get Bedrock client (singleton)"""
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client('bedrock-runtime', region_name=BEDROCK_REGION)
    return _bedrock_client


def get_s3_client():
    """Get S3 client (singleton)"""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client('s3')
    return _s3_client


def get_dynamodb():
    """Get DynamoDB resource (singleton)"""
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource('dynamodb')
    return _dynamodb


def get_receipts_table():
    """Get receipts table (singleton)"""
    global _receipts_table
    if _receipts_table is None and DYNAMODB_TABLE_NAME:
        _receipts_table = get_dynamodb().Table(DYNAMODB_TABLE_NAME)
    return _receipts_table


def setup_logging():
    """Setup logging configuration"""
    logging.basicConfig(
        level=logging.INFO,
        format='[%(levelname)s] %(name)s: %(message)s',
        force=True
    )


# LLM Prompts
RECEIPT_ANALYSIS_PROMPT = """Analyze this receipt image carefully and extract structured data. Think through the analysis step-by-step internally:

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