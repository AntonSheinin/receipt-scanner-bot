from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, List

@dataclass
class LineItem:
    """Receipt line item"""
    name: str
    price: Decimal
    quantity: int = 1
    category: Optional[str] = None

@dataclass
class OCRResponse:
    """OCR processing response"""
    raw_text: str
    store_name: Optional[str] = None
    date: Optional[str] = None
    receipt_number: Optional[str] = None
    total: Optional[Decimal] = None
    payment_method: Optional[str] = None
    items: List[LineItem] = None
    confidence: float = 0.0
    success: bool = True
    error_message: Optional[str] = None
    
    def __post_init__(self):
        if self.items is None:
            self.items = []

class OCRProvider(ABC):
    """Base OCR provider interface"""
    
    @abstractmethod
    def extract_text(self, image_data: bytes) -> OCRResponse:
        """Extract raw text from image"""
        pass
    
    @abstractmethod
    def extract_receipt_data(self, image_data: bytes) -> OCRResponse:
        """Extract structured receipt data"""
        pass