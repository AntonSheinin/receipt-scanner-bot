"""
    Configuration and Constants
"""

import os
import json
import logging
import boto3
from functools import lru_cache


# ---------- App Configuration -----------------------
AWS_REGION = 'eu-west-1'
BEDROCK_MODEL_ID = 'eu.anthropic.claude-3-7-sonnet-20250219-v1:0' # eu.anthropic.claude-sonnet-4-20250514-v1:0
BEDROCK_REGION = 'eu-west-1'
LLM_PROVIDER = 'bedrock'  # Options: bedrock, openai
DOCUMENT_STORAGE_PROVIDER = 'postgresql'  # Options: postgresql

# OCR Configuration
OCR_PROVIDER = 'google_vision' # Options: aws_textract, google_vision
OCR_PROCESSING_MODE = 'structured_text'  # Options: raw_text, structured_text
OPENAI_MODEL_ID = 'gpt-5-nano-2025-08-07' # gpt-5-chat-latest, gpt-4.1-2025-04-14, gpt-5-nano-2025-08-07

# Document Processing Mode
DOCUMENT_PROCESSING_MODE = 'ocr_llm'  # Options: llm, ocr_llm, pp_ocr_llm
# ------------------------------------------------------


# Limits
MAX_MESSAGE_LENGTH = 4000
MAX_ITEMS_DISPLAY = 10
MAX_ITEM_NAME_LENGTH = 20
MAX_RECEIPTS_PER_USER = 100

# --------------- Configuration from lambda environment variables --------------
DB_HOST = os.environ.get('DB_HOST')
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME', '')
SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL', '')
STAGE = os.environ.get('STAGE')
# ------------------------------------------------------------------------------

DATABASE_NAMES = {
    'dev': 'receipt_scanner_dev',
    'prod': 'receipt_scanner_prod'
}

# AWS Clients (singleton pattern)
_bedrock_client = None
_s3_client = None
_sqs_client = None

# ------------- Secrets Management (stored in AWS Secrets Manager)-------------
@lru_cache(maxsize=1)
def get_secrets() -> dict:
    """Get all secrets from AWS Secrets Manager (cached)"""
    client = boto3.client('secretsmanager')
    secret_name = f"receipt-scanner-bot-{STAGE}"

    try:
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response['SecretString'])

    except Exception as e:
        logging.error(f"Failed to get secrets: {e}")
        raise

_secrets = get_secrets()
TELEGRAM_BOT_TOKEN = _secrets["TELEGRAM_BOT_TOKEN"]
DB_USER = _secrets["DB_USER"]
DB_PASSWORD = _secrets["DB_PASSWORD"]
OPENAI_API_KEY = _secrets["OPENAI_API_KEY"]
GOOGLE_CREDENTIALS_JSON = _secrets["GOOGLE_CREDENTIALS_JSON"]
USER_ID_SALT = _secrets["USER_ID_SALT"]
# ----------------------------------------------------------------------------

# Database connection info
def get_database_connection_info() -> dict:
    return {
        'host': DB_HOST,
        'port': 5432,
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
