"""
Configuration and Constants
"""
import os
import logging
import boto3


# Environment variables
AWS_REGION = os.environ.get('AWS_REGION')
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
BEDROCK_MODEL_ID = os.environ.get('BEDROCK_MODEL_ID')
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME')
BEDROCK_REGION = os.environ.get('BEDROCK_REGION')

LLM_PROVIDER = os.environ.get('LLM_PROVIDER')

# OCR Configuration
OCR_PROVIDER = os.environ.get('OCR_PROVIDER')
OCR_PROCESSING_MODE = os.environ.get('OCR_PROCESSING_MODE')

# Document Processing Mode
DOCUMENT_PROCESSING_MODE = os.environ.get('DOCUMENT_PROCESSING_MODE')

# Message limits
MAX_MESSAGE_LENGTH = 4000
MAX_ITEMS_DISPLAY = 10
MAX_ITEM_NAME_LENGTH = 20

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
