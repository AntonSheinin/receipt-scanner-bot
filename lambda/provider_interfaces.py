from abc import ABC, abstractmethod
from typing import Optional, List
from dataclasses import dataclass
from decimal import Decimal

@dataclass
class LLMResponse:
    content: str
    usage_tokens: Optional[int] = None

@dataclass
class LineItem:
    name: str
    price: Decimal
    quantity: int = 1
    category: Optional[str] = None

@dataclass
class OCRResponse:
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
    
    @abstractmethod
    def generate_url(self, key: str, expires_in: int = 3600) -> Optional[str]:
        """Generate presigned URL"""
        pass

class DocumentStorage(ABC):
    """Interface for storing and retrieving documents/records"""
    
    @abstractmethod
    def put(self, table: str, item: Dict[str, Any]) -> bool:
        """Store document"""
        pass
    
    @abstractmethod
    def get(self, table: str, key: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Retrieve document by key"""
        pass
    
    @abstractmethod
    def query(self, table: str, key_condition: Dict[str, Any], 
              filter_expression: Optional[Dict] = None,
              index_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Query documents"""
        pass
    
    @abstractmethod
    def scan(self, table: str, filter_expression: Optional[Dict] = None,
             limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Scan all documents"""
        pass
    
    @abstractmethod
    def delete(self, table: str, key: Dict[str, Any]) -> bool:
        """Delete document"""
        pass
    
    @abstractmethod
    def batch_write(self, table: str, items: List[Dict[str, Any]]) -> bool:
        """Batch write documents"""
        pass