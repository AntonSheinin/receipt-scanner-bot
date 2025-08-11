"""
    Common Utility Functions
"""

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional, Union
import uuid
from config import USER_ID_SALT
import logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def convert_floats_to_decimals(obj: Any) -> Any:
    """
        Recursively convert float and numeric values to Decimal for DynamoDB storage
    """
    if obj is None:
        return None
    elif isinstance(obj, (int, float)):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: convert_floats_to_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimals(item) for item in obj]
    else:
        return obj

def convert_decimals_to_floats(obj: Any) -> Any:
    """
        Recursively convert Decimal objects to float
    """

    if isinstance(obj, Decimal):
        return float(obj)

    if isinstance(obj, dict):
        return {k: convert_decimals_to_floats(v) for k, v in obj.items()}

    if isinstance(obj, list):
        return [convert_decimals_to_floats(v) for v in obj]

    return obj

def safe_float(value: Any) -> float:
    """Safely convert value to float"""
    try:
        return float(value) if value is not None else 0.0
    except (ValueError, TypeError):
        return 0.0

def safe_int(value: Any) -> int:
    """Safely convert value to int"""
    try:
        return int(value) if value is not None else 1
    except (ValueError, TypeError):
        return 1

def safe_string_value(value: Any, default: str) -> str:
    if value and isinstance(value, str) and value.strip():
        return value.strip()
    return default

def normalize_date(date_str: str) -> Optional[str]:
        """Normalize date to YYYY-MM-DD format"""
        if not date_str:
            return None

        formats = ['%d/%m/%Y', '%m/%d/%Y', '%Y-%m-%d', '%d-%m-%Y']

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue

        return date_str  # Return as-is if can't parse

def create_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    """
        Create Lambda response
    """

    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body)
    }

def get_secure_user_id(telegram_user_id: Union[str, int]) -> str:
    """
    Generate secure, deterministic user ID using UUID5

    Args:
        telegram_user_id: Original Telegram user/chat ID (int or str)

    Returns:
        Secure UUID-based ID (32 characters hex, collision-resistant)
        Same input always produces same output for queryability
    """
    try:
        # Normalize input to string
        user_str = str(telegram_user_id).strip()

        if not user_str:
            raise ValueError("Empty user ID provided")

        # Create namespace UUID from salt (deterministic)
        namespace = uuid.uuid5(uuid.NAMESPACE_DNS, USER_ID_SALT)

        # Generate deterministic UUID5 based on user_id
        secure_uuid = uuid.uuid5(namespace, user_str)

        # Return as hex string (32 characters, no hyphens)
        return secure_uuid.hex

    except Exception as e:
        logger.error(f"Error generating secure user ID: {e}")
        # Fallback to original (not recommended for production)
        logger.warning("Falling back to original user ID - CHECK USER_ID_SALT configuration!")
        return str(telegram_user_id)
