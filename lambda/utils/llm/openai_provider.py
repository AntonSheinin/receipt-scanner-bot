from typing import Optional, List, Dict, Any
import base64
import logging
from openai import OpenAI
from provider_interfaces import LLMProvider, LLMResponse
from config import setup_logging
import os

setup_logging()
logger = logging.getLogger(__name__)

class OpenAIProvider(LLMProvider):
    def __init__(self):
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")

        self.client = OpenAI(api_key=api_key)
        self.model_id = os.getenv('OPENAI_MODEL_ID', '')

    def generate_text(self, prompt: str, max_tokens: int = 3000) -> Optional[LLMResponse]:
        """Generate text response from prompt"""

        logger.info(f"Generating text with OpenAI model: {self.model_id}")

        try:
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=max_tokens,
                # temperature=0.1
            )

            if response.choices and response.choices[0].message.content:
                content = response.choices[0].message.content
                usage_tokens = response.usage.completion_tokens if response.usage else None

                return LLMResponse(content=content, usage_tokens=usage_tokens)

            return None

        except Exception as e:
            logger.error(f"OpenAI text generation error: {e}")
            return None

    def analyze_image(self, image_data: bytes, prompt: str, max_tokens: int = 3000) -> Optional[LLMResponse]:
        """Analyze image with prompt"""

        logger.info(f"Analyzing image with OpenAI model: {self.model_id}")

        try:
            # Convert image to base64
            image_base64 = base64.b64encode(image_data).decode('utf-8')

            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_completion_tokens=max_tokens,
                # temperature=0.1
            )

            if response.choices and response.choices[0].message.content:
                content = response.choices[0].message.content
                usage_tokens = response.usage.completion_tokens if response.usage else None

                return LLMResponse(content=content, usage_tokens=usage_tokens)

            return None

        except Exception as e:
            logger.error(f"OpenAI image analysis error: {e}")
            return None
