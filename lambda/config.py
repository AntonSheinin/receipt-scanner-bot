"""
    Configuration and Constants
"""

import os
import json
import logging
import boto3


# Environment variables
AWS_REGION = os.environ.get('AWS_REGION')
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
BEDROCK_MODEL_ID = os.environ.get('BEDROCK_MODEL_ID')
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
BEDROCK_REGION = os.environ.get('BEDROCK_REGION')

USER_ID_SALT = os.environ.get('USER_ID_SALT', 'receipt-scanner-bot-default-salt-change-in-production')

LLM_PROVIDER = os.environ.get('LLM_PROVIDER')
DOCUMENT_STORAGE_PROVIDER = os.environ.get('DOCUMENT_STORAGE_PROVIDER')

# OCR Configuration
OCR_PROVIDER = os.environ.get('OCR_PROVIDER')
OCR_PROCESSING_MODE = os.environ.get('OCR_PROCESSING_MODE')

# Document Processing Mode
DOCUMENT_PROCESSING_MODE = os.environ.get('DOCUMENT_PROCESSING_MODE')

# Message limits
MAX_MESSAGE_LENGTH = 4000
MAX_ITEMS_DISPLAY = 10
MAX_ITEM_NAME_LENGTH = 20

MAX_RECEIPTS_PER_USER = 100

# Database Configuration
DB_USER = os.environ.get('DB_USER')
DB_PASSWORD = os.environ.get('DB_PASSWORD')
DB_PORT = os.environ.get('DB_PORT', 5432)
DB_HOST = os.environ.get('DB_HOST')

STAGE = os.environ.get('STAGE')

DATABASE_NAMES = {
    'dev': 'receipt_scanner_dev',
    'prod': 'receipt_scanner_prod'
}

# AWS Clients (singleton pattern)
_bedrock_client = None
_s3_client = None
_sqs_client = None

SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL')


def get_database_connection_info():
    """Get database connection info from environment variables"""
    return {
        'host': DB_HOST,
        'port': DB_PORT,
        'database': DATABASE_NAMES[STAGE],
        'user': DB_USER,
        'password': DB_PASSWORD
    }


def get_sqs_client():
    """Get SQS client (singleton)"""
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = boto3.client('sqs')
    return _sqs_client


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


def setup_logging():
    """Setup logging configuration"""
    logging.basicConfig(
        level=logging.INFO,
        format='[%(levelname)s] %(name)s: %(message)s',
        force=True
    )
