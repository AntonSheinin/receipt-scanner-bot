"""
    Common Utility Functions
"""

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional, Union, Dict
import uuid
from config import USER_ID_SALT
import logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

def create_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Create Lambda response in API Gateway format"""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(body),
        "isBase64Encoded": False
    }

