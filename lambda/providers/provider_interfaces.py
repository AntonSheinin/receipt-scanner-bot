"""
    Provider Interfaces for various service providers
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field


@dataclass
class LLMResponse:
    content: str
    usage_tokens: Optional[int] = None

@dataclass
class OCRResponse:
    raw_text: str
    store_name: Optional[str] = None
    date: Optional[str] = None
    receipt_number: Optional[str] = None
    total: Optional[float] = None
    payment_method: Optional[str] = None
    items: List[Dict] = field(default_factory=list)
    confidence: float = 0.0
    success: bool = True
    error_message: Optional[str] = None

    def __post_init__(self):
        if self.items is None:
            self.items = []

class LLMProvider(ABC):
    @abstractmethod
    def generate_text(self, prompt: str, max_tokens: int = 1000) -> Optional[LLMResponse]:
        pass

    @abstractmethod
    def analyze_image(self, image_data: bytes, prompt: str, max_tokens: int = 2000) -> Optional[LLMResponse]:
        pass


class OCRProvider(ABC):
    @abstractmethod
    def extract_raw_text(self, image_data: bytes) -> OCRResponse:
        pass

    @abstractmethod
    def extract_receipt_data(self, image_data: bytes) -> OCRResponse:
        pass

class ImageStorage(ABC):
    """Interface for storing and retrieving images"""

    @abstractmethod
    def store(self, key: str, image_data: bytes, metadata: Optional[Dict] = None) -> Optional[str]:
        """Store image and return URL/path"""
        pass

    @abstractmethod
    def retrieve(self, key: str) -> Optional[bytes]:
        """Retrieve image data"""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete image"""
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if image exists"""
        pass

class DocumentStorage(ABC):
    """Interface for storing and retrieving documents/records"""

    # ======================
    # Core Receipt Operations
    # ======================

    @abstractmethod
    def save_receipt_with_items(self, user_id: str, receipt_data: Dict[str, Any]) -> bool:
        """Store receipt with all its items in one operation"""
        pass

    @abstractmethod
    def get_filtered_receipts(self, user_id: str, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Get receipts with optional filtering using SQL optimization

        If filters is None or empty, returns all user receipts.

        filters format:
        {
            'date_range': {'start': '2024-01-01', 'end': '2024-12-31'},
            'store_names': ['רמי לוי', 'שופרסל'],
            'categories': ['food', 'beverages'],
            'subcategories': ['dairy_eggs', 'bread_bakery'],
            'item_keywords': ['חלב', 'לחם'],
            'payment_methods': ['cash', 'credit_card'],
            'price_range': {'min': 10, 'max': 100},
            'limit': 50
        }
        """
        pass

    @abstractmethod
    def delete_receipt(self, user_id: str, receipt_id: str) -> bool:
        """Delete specific receipt (items cascade automatically)"""
        pass

    # ======================
    # Efficient Bulk Operations
    # ======================

    @abstractmethod
    def delete_last_uploaded_receipt(self, user_id: str) -> Optional[str]:
        """Delete most recent receipt and return image_url for cleanup

        Returns the image_url of the deleted receipt or None if no receipts found.
        Should use SQL ORDER BY created_at DESC LIMIT 1 for efficiency.
        """
        pass

    @abstractmethod
    def delete_all_receipts(self, user_id: str) -> List[str]:
        """Delete all user receipts and return image_urls for cleanup

        Returns list of image_urls for the deleted receipts (excluding nulls).
        Should use SQL RETURNING clause for efficiency.
        """
        pass

    @abstractmethod
    def count_user_receipts(self, user_id: str) -> int:
        """Count total receipts for user using efficient SQL COUNT()

        This should use SELECT COUNT(*) FROM receipts WHERE user_id = ?
        and NOT pull any actual receipt data for performance.
        """
        pass
