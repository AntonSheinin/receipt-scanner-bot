"""
    Common Utility Functions
"""

import json
from decimal import Decimal
from typing import Any, Optional

def convert_decimals(obj: Any) -> Any:
    """
        Recursively convert Decimal objects to float
    """

    if isinstance(obj, Decimal):
        return float(obj)
    
    if isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    
    if isinstance(obj, list):
        return [convert_decimals(v) for v in obj]
    
    return obj


def create_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    """
        Create Lambda response
    """

    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body)
    }


def safe_get(dictionary: Optional[dict[Any, Any]], key: str, default: Any = None) -> Any:
    """
        Safely get value from dictionary
    """

    return dictionary.get(key, default) if dictionary else default


def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """
        Truncate string if longer than max_length
    """

    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def format_price(price: Any) -> str:
    """
        Format price for display
    """

    try:
        return f"{float(price):.2f}"
    
    except (ValueError, TypeError):
        return "$0.00"


def clean_hebrew_text(text: str) -> str:
    """
        Clean Hebrew text for proper Unicode handling
    """

    if isinstance(text, str):
        return text.encode('utf-8').decode('utf-8')
    
    return text