from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass

@dataclass
class LLMResponse:
    content: str
    usage_tokens: Optional[int] = None

class LLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    @abstractmethod
    def generate_text(self, prompt: str, max_tokens: int = 1000) -> Optional[LLMResponse]:
        """Generate text response from prompt"""
        pass
    
    @abstractmethod
    def analyze_image(self, image_data: bytes, prompt: str, max_tokens: int = 2000) -> Optional[LLMResponse]:
        """Analyze image with text prompt"""
        pass

    @abstractmethod
    def _invoke_model(self, messages: list, max_tokens: int) -> Optional[LLMResponse]:
        """Invoke the underlying LLM model"""
        pass