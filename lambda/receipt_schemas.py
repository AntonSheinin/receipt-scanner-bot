"""
Pydantic schemas for receipt data validation
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Literal
from decimal import Decimal, InvalidOperation
from datetime import datetime
import re


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
    category: Optional[Literal[
        "food", "beverages", "household", "electronics",
        "clothing", "pharmacy", "deposit", "other"
    ]] = Field(
        default="other",
        description="Item category"
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
            raise ValueError("Item name cannot be empty")
        return cleaned

    @field_validator('price', 'discount')
    @classmethod
    def validate_decimals(cls, v) -> Decimal:
        """Ensure proper decimal handling"""
        if isinstance(v, (int, float)):
            return Decimal(str(v))
        elif isinstance(v, str):
            try:
                return Decimal(v)
            except InvalidOperation:
                raise ValueError(f"Invalid decimal value: {v}")
        return v

    @field_validator('discount')
    @classmethod
    def validate_discount(cls, v: Decimal) -> Decimal:
        """Discount should be non-positive (0 or negative)"""
        if v > 0:
            # Auto-correct positive discounts to negative
            return -v
        return v

    @model_validator(mode='after')
    def validate_item_totals(self) -> 'ReceiptItem':
        """Validate item price calculations"""
        if self.price < 0:
            raise ValueError("Item price cannot be negative")

        # Calculate expected total for logging/validation
        expected_total = (self.price * self.quantity) + self.discount
        if expected_total < 0:
            # Log warning but don't fail - some items might have full refunds
            pass

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
            raise ValueError("Store name cannot be empty")
        return cleaned

    @field_validator('date')
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        """Validate date format and ensure it's not more than 6 months old"""
        cleaned = v.strip()
        if not cleaned:
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
            raise ValueError(f"Invalid date format: {cleaned}")

        # Check if date is not more than 6 months from now
        from datetime import timedelta
        six_months_ago = datetime.now() - timedelta(days=180)
        tomorrow = datetime.now() + timedelta(days=1)

        if parsed_date < six_months_ago:
            raise ValueError(f"Receipt date is too old (more than 6 months): {normalized_date}")

        if parsed_date > tomorrow:
            raise ValueError(f"Receipt date is in the future: {normalized_date}")

        return normalized_date

    @field_validator('total')
    @classmethod
    def validate_total(cls, v) -> Decimal:
        """Validate total amount"""
        if isinstance(v, (int, float)):
            total_decimal = Decimal(str(v))
        elif isinstance(v, str):
            try:
                total_decimal = Decimal(v)
            except InvalidOperation:
                raise ValueError(f"Invalid total amount: {v}")
        else:
            total_decimal = v

        if total_decimal < 0:
            raise ValueError("Total amount cannot be negative")

        return total_decimal

    @field_validator('receipt_number')
    @classmethod
    def clean_receipt_number(cls, v: Optional[str]) -> Optional[str]:
        """Clean receipt number field"""
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned if cleaned else None

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
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

        # If we have items and total, they must match closely
        if self.items and self.total is not None:
            calculated_total = sum(
                (item.price * item.quantity) + item.discount
                for item in self.items
            )

            # Allow for small rounding differences (max 0.10 currency units)
            difference = abs(calculated_total - self.total)
            if difference > Decimal('0.10'):
                raise ValueError(
                    f"Total amount ({self.total}) doesn't match sum of items ({calculated_total}). "
                    f"Difference: {difference}"
                )

        return self

    def model_dump_for_storage(self) -> dict:
        """Convert to dict format suitable for DynamoDB storage"""
        return self.model_dump(mode='json')

    def get_json_schema(self) -> dict:
        """Get JSON schema for LLM structured output"""
        return self.model_json_schema()


class ReceiptAnalysisResult(BaseModel):
    """Complete receipt analysis result with metadata"""

    receipt_data: ReceiptData
    raw_text: Optional[str] = Field(
        default=None,
        description="Original OCR text"
    )
    processing_metadata: Optional[dict] = Field(
        default_factory=dict,
        description="Processing metadata and debug info"
    )

    @classmethod
    def from_llm_response(cls, llm_data: dict, raw_text: str = None, processing_method: str = None) -> 'ReceiptAnalysisResult':
        """Create from LLM response with strict validation - no partial results"""

        # Add processing metadata
        if processing_method:
            llm_data['processing_method'] = processing_method

        # Strict validation - either it passes completely or we fail
        receipt_data = ReceiptData(**llm_data)

        return cls(
            receipt_data=receipt_data,
            raw_text=raw_text,
            processing_metadata={
                'processing_method': processing_method,
                'validation_timestamp': datetime.now().isoformat(),
                'validation_status': 'success'
            }
        )


def get_receipt_json_schema() -> dict:
    """Get JSON schema for LLM structured output"""
    return ReceiptData.model_json_schema()
