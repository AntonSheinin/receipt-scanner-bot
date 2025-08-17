"""
Pydantic schemas for receipt data validation
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Literal
from decimal import Decimal, InvalidOperation
from config.categories import category_manager
from datetime import datetime
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
    date: str = Field(
        pattern=r'^\d{4}-\d{2}-\d{2}$',
        description="Receipt date in YYYY-MM-DD format (required)"
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
    processing_method: Optional[str] = Field(
        default=None,
        description="How the receipt was processed (llm, ocr_llm, etc.)"
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="OCR confidence score (0-100)"
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

    @field_validator('date')
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        """Validate date format and ensure it's not more than 6 months old"""
        cleaned = v.strip()
        if not cleaned:
            logger.error("Date validation failed: empty date provided")
            raise ValueError("Date cannot be empty")

        # Try to parse various date formats and normalize to YYYY-MM-DD
        date_patterns = [
            (r'^(\d{4})-(\d{2})-(\d{2})$', '%Y-%m-%d'),  # Already correct
            (r'^(\d{2})/(\d{2})/(\d{4})$', '%d/%m/%Y'),  # DD/MM/YYYY
            (r'^(\d{2})\.(\d{2})\.(\d{4})$', '%d.%m.%Y'), # DD.MM.YYYY
            (r'^(\d{2})-(\d{2})-(\d{4})$', '%d-%m-%Y'),  # DD-MM-YYYY
        ]

        parsed_date = None
        normalized_date = None

        for pattern, date_format in date_patterns:
            if re.match(pattern, cleaned):
                try:
                    parsed_date = datetime.strptime(cleaned, date_format)
                    normalized_date = parsed_date.strftime('%Y-%m-%d')
                    break

                except ValueError:
                    continue

        if not parsed_date:
            logger.error(f"Date validation failed: invalid format '{cleaned}'")
            raise ValueError(f"Invalid date format: {cleaned}")

        # Check if date is not more than 6 months from now
        from datetime import timedelta
        six_months_ago = datetime.now() - timedelta(days=180)
        tomorrow = datetime.now() + timedelta(days=1)

        if parsed_date < six_months_ago:
            logger.error(f"Date validation: receipt date is old (more than 6 months): {normalized_date}")
            raise ValueError(f"Receipt date is too old (more than 6 months): {normalized_date}")

        if parsed_date > tomorrow:
            logger.error(f"Date validation failed: future date provided: {normalized_date}")
            raise ValueError(f"Receipt date is in the future: {normalized_date}")

        return normalized_date

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
        if not self.date:
            missing_fields.append("date")
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

        # Log processing metadata if available
        if self.processing_method:
            logger.info(f"Receipt processed using method: {self.processing_method}")

        if self.confidence is not None:
            logger.info(f"Receipt processing confidence: {self.confidence}%")

        return self

    def model_dump_for_storage(self) -> dict:
        """Convert to dict format suitable for DynamoDB storage"""
        storage_data = self.model_dump(mode='json')

        logger.info(f"Receipt prepared for storage: store='{self.store_name}', items={len(self.items)}, size={len(str(storage_data))} chars")


        return storage_data

    def get_json_schema(self) -> dict:
        """Get JSON schema for LLM structured output"""
        schema = self.model_json_schema()
        logger.debug("Generated JSON schema for LLM structured output")
        return schema

    def get_summary(self) -> str:
        """Get human-readable receipt summary for logging"""
        summary = f"Receipt: {self.store_name} | {self.date} | {len(self.items)} items | Total: {self.total} | Payment: {self.payment_method}"
        if self.receipt_number:
            summary += f" | Ref: {self.receipt_number}"
        return summary


