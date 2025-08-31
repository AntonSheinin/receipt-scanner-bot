"""
    Pydantic schemas for receipt data validation
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Literal, Dict, Any
from decimal import Decimal, InvalidOperation
from providers.category_manager import category_manager
from datetime import datetime, timedelta, timezone, date
from dateutil import parser as date_parser
import re
import logging
from config import setup_logging


setup_logging()
logger = logging.getLogger(__name__)

class ReceiptItem(BaseModel):
    """Individual receipt item with validation"""

    name: str = Field(
        min_length=1,
        max_length=200,
        description="Item name (Hebrew/English supported)"
    )
    price: Decimal = Field(
        ge=0,
        decimal_places=2,
        description="Original unit price before discount"
    )
    quantity: Decimal = Field(
        gt=0,
        default=1.0,
        decimal_places=3,
        description="Quantity purchased (supports fractional weights)"
    )
    category: str = Field(
        description="Main category (auto-filled from subcategory)"
    )
    subcategory: str = Field(
        description="Subcategory from predefined taxonomy"
    )
    discount: Decimal = Field(
        default=0.0,
        decimal_places=2,
        description="Discount amount (negative value)"
    )

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Clean and validate item name"""
        cleaned = v.strip()
        if not cleaned:
            logger.error("Item name validation failed: empty name provided")
            raise ValueError("Item name cannot be empty")

        return cleaned

    @field_validator('subcategory')
    @classmethod
    def validate_subcategory(cls, v: str) -> str:
        """Validate subcategory against taxonomy - fail if invalid"""
        if not v or not v.strip():
            logger.error("Subcategory validation failed: empty subcategory provided")
            raise ValueError("Subcategory cannot be empty")

        subcategory = v.strip().lower()

        # Check if subcategory exists in taxonomy
        valid_subcategories = category_manager.get_all_subcategories()
        if subcategory not in valid_subcategories:
            logger.error(f"Subcategory validation failed: '{subcategory}' not in taxonomy. Valid options: {', '.join(valid_subcategories[:10])}...")
            raise ValueError(f"Invalid subcategory '{subcategory}'. Must be one of: {', '.join(valid_subcategories)}")

        return subcategory

    @model_validator(mode='after')
    def auto_fill_category(self) -> 'ReceiptItem':
        """Auto-fill main category from subcategory"""
        self.category = category_manager.get_category_from_subcategory(self.subcategory)

        return self

    def model_dump_for_storage(self) -> dict:
        """Storage format with both category and subcategory"""
        storage_data = {
            'name': self.name,
            'price': float(self.price),
            'quantity': float(self.quantity),
            'category': self.category,
            'subcategory': self.subcategory,
            'discount': float(self.discount)
        }
        return storage_data

    @field_validator('price', 'discount')
    @classmethod
    def validate_decimals(cls, v) -> Decimal:
        """Ensure proper decimal handling"""
        try:
            if isinstance(v, (int, float)):
                result = Decimal(str(v))
            elif isinstance(v, str):
                result = Decimal(v)
            else:
                result = v

            return result

        except InvalidOperation:
            logger.error(f"Decimal validation failed: invalid value '{v}'")
            raise ValueError(f"Invalid decimal value: {v}")

    @field_validator('discount')
    @classmethod
    def validate_discount(cls, v: Decimal) -> Decimal:
        """Discount should be non-positive (0 or negative)"""
        if v > 0:
            # Auto-correct positive discounts to negative
            corrected = -v
            logger.warning(f"Discount auto-corrected from positive {v} to negative {corrected}")
            return corrected

        logger.debug(f"Discount validated: {v}")
        return v

    @model_validator(mode='after')
    def validate_item_totals(self) -> 'ReceiptItem':
        """Validate item price calculations"""
        if self.price < 0:
            logger.error(f"Item price validation failed: negative price {self.price} for item '{self.name}'")
            raise ValueError("Item price cannot be negative")

        # Calculate expected total for logging/validation
        expected_total = (self.price * self.quantity) + self.discount
        if expected_total < 0:
            logger.warning(f"Item '{self.name}' has negative total: {expected_total} (price: {self.price}, quantity: {self.quantity}, discount: {self.discount})")

        return self

class ReceiptData(BaseModel):
    """Complete receipt data with validation"""

    store_name: str = Field(
        min_length=1,
        max_length=100,
        description="Store/business name (required)"
    )
    purchasing_date: date = Field(
        description="Receipt date (required)"
    )

    payment_method: Literal["cash", "credit_card", "other"] = Field(
        description="Payment method used (required)"
    )
    total: Decimal = Field(
        ge=0,
        decimal_places=2,
        description="Total receipt amount (required)"
    )
    receipt_number: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Receipt/transaction number"
    )
    items: List[ReceiptItem] = Field(
        default_factory=list,
        description="List of receipt items (can be empty for simple receipts)"
    )


    @field_validator('store_name')
    @classmethod
    def validate_store_name(cls, v: str) -> str:
        """Clean and validate store name"""
        cleaned = v.strip()
        if not cleaned:
            logger.error("Store name validation failed: empty store name provided")
            raise ValueError("Store name cannot be empty")

        return cleaned

    @field_validator("purchasing_date", mode="before")
    def validate_and_parse_date(cls, v: str) -> date:
        """Convert string to date and validate constraints"""

        # Try parsing with dateutil (handles most formats automatically)
        try:
            parsed = date_parser.parse(v, dayfirst=False).date()
        except Exception:
            raise ValueError("Unrecognized date format")

        today = date.today()
        six_months_ago = today - timedelta(days=180)  # strict ~6 months window

        if parsed > today:
            raise ValueError("Date cannot be in the future")

        if parsed < six_months_ago:
            raise ValueError("Date cannot be older than 6 months")

        return parsed

    @field_validator('payment_method')
    @classmethod
    def validate_payment_method(cls, v: str) -> str:
        """Validate payment method against allowed values"""

        if not v or not v.strip():
            logger.error("Payment method validation failed: empty payment method provided")
            raise ValueError("Payment method cannot be empty")

        cleaned = v.strip().lower()
        valid_methods = ["cash", "credit_card", "other"]

        if cleaned not in valid_methods:
            logger.error(f"Payment method validation failed: '{cleaned}' not in allowed values: {valid_methods}")
            raise ValueError(f"Invalid payment method '{cleaned}'. Must be one of: {', '.join(valid_methods)}")

        return cleaned

    @field_validator('total')
    @classmethod
    def validate_total(cls, v) -> Decimal:
        """Validate total amount"""
        try:
            if isinstance(v, (int, float)):
                total_decimal = Decimal(str(v))
            elif isinstance(v, str):
                total_decimal = Decimal(v)
            else:
                total_decimal = v

            if total_decimal < 0:
                logger.error(f"Total validation failed: negative amount {total_decimal}")
                raise ValueError("Total amount cannot be negative")

            return total_decimal
        except InvalidOperation:
            logger.error(f"Total validation failed: invalid decimal value '{v}'")
            raise ValueError(f"Invalid total amount: {v}")

    @field_validator('receipt_number')
    @classmethod
    def clean_receipt_number(cls, v: Optional[str]) -> Optional[str]:
        """Clean receipt number field"""
        if v is None:
            logger.warning("Receipt number: None (optional field)")
            return None

        cleaned = v.strip()
        result = cleaned if cleaned else None
        return result

    @field_validator('items')
    @classmethod
    def validate_items(cls, v: List[ReceiptItem]) -> List[ReceiptItem]:
        """Validate items list"""
        if v:
            # Log category distribution
            categories = {}
            for item in v:
                categories[item.category] = categories.get(item.category, 0) + 1

        return v

    @model_validator(mode='after')
    def validate_receipt_consistency(self) -> 'ReceiptData':
        """Strict validation - require core fields and validate totals"""

        # Core required fields for any valid receipt
        missing_fields = []
        if not self.store_name or not self.store_name.strip():
            missing_fields.append("store_name")
        if self.total is None:
            missing_fields.append("total")
        if not self.purchasing_date:
            missing_fields.append("purchasing_date")
        if not self.payment_method:
            missing_fields.append("payment_method")

        if missing_fields:
            logger.error(f"Receipt validation failed: missing required fields: {', '.join(missing_fields)}")
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

        # If we have items and total, they must match closely
        if self.items and self.total is not None:
            calculated_total = sum(
                (item.price * item.quantity) + item.discount
                for item in self.items
            )

            # Allow for small rounding differences (max 0.10 currency units)
            difference = abs(calculated_total - self.total)

            logger.debug(f"Total validation: receipt total={self.total}, calculated total={calculated_total}, difference={difference}")

            if difference > Decimal('0.10'):
                logger.error(f"Receipt validation failed: total mismatch. Expected: {self.total}, Calculated: {calculated_total}, Difference: {difference}")
                raise ValueError(
                    f"Total amount ({self.total}) doesn't match sum of items ({calculated_total}). "
                    f"Difference: {difference}"
                )
            elif difference > 0:
                logger.warning(f"Small total discrepancy detected: {difference} (within tolerance)")

        return self

    def get_json_schema(self) -> dict:
        """Get JSON schema for LLM structured output"""
        schema = self.model_json_schema()
        logger.debug("Generated JSON schema for LLM structured output")
        return schema

    def get_summary(self) -> str:
        """Get human-readable receipt summary for logging"""
        summary = f"Receipt: {self.store_name} | {self.purchasing_date} | {len(self.items)} items | Total: {self.total} | Payment: {self.payment_method}"
        if self.receipt_number:
            summary += f" | Ref: {self.receipt_number}"
        return summary

class ReceiptAnalysisResult(BaseModel):
    """Container for receipt analysis results with metadata"""

    receipt_data: ReceiptData = Field(description="Validated receipt data")
    raw_text: Optional[str] = Field(default=None, description="Raw OCR text if available")
    processing_metadata: Optional[Dict[str, Any]] = Field(default=None, description="Processing metadata")

    @classmethod
    def from_llm_response(cls, llm_data: Dict[str, Any], raw_text: Optional[str] = None) -> 'ReceiptAnalysisResult':
        """Create validated result from LLM response data"""

        # Convert items to use subcategory field for backward compatibility
        if 'items' in llm_data and llm_data['items']:
            for item in llm_data['items']:
                if 'category' in item and 'subcategory' not in item:
                    # Map old category to subcategory
                    item['subcategory'] = item['category']

        receipt_data = ReceiptData(**llm_data)

        return cls(
            receipt_data=receipt_data,
            raw_text=raw_text,
        )


