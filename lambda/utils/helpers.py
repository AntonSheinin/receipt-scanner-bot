"""
    Common Utility Functions
"""

import json
from decimal import Decimal
from typing import Any, Optional

def convert_floats_to_decimals(obj: Any) -> Any:
    """
        Recursively convert float and numeric values to Decimal for DynamoDB storage
    """
    if obj is None:
        return None
    elif isinstance(obj, (int, float)):
        return Decimal(str(obj))
    elif isinstance(obj, str):
        # Try to convert numeric strings to Decimal
        try:
            if '.' in obj or obj.isdigit():
                float(obj)  # Validate it's a valid number
                return Decimal(obj)
        except ValueError:
            pass
        return obj
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

def create_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    """
        Create Lambda response
    """

    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body)
    }
