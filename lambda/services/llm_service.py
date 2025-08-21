"""
    LLM Service module
"""

import re
from typing import Dict, Optional
import logging
import json
from config import setup_logging
from provider_factory import ProviderFactory
from provider_interfaces import LLMResponse
from utils.llm.prompts import PromptManager
from receipt_schemas import ReceiptAnalysisResult
from pydantic import ValidationError


setup_logging()
logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self, provider_name: str):
        self.provider = ProviderFactory.create_llm_provider(provider_name)
        self.prompt_manager = PromptManager()

    def analyze_receipt(self, image_data: bytes) -> Optional[ReceiptAnalysisResult]:
        """Analyze receipt image"""

        logger.info("Analyzing receipt image with LLM")

        prompt = self.prompt_manager.get_receipt_analysis_prompt()
        response = self.provider.analyze_image(image_data, prompt)

        logger.info(f"LLM response: {response.content if response else 'No response'}")

        # Parse JSON and validate with Pydantic
        return self._create_validated_result(
            response.content,
        ) if response else None

    def structure_ocr_text(self, ocr_text: str) -> Optional[ReceiptAnalysisResult]:
        """Structure OCR text with Pydantic validation"""

        logger.info("Structuring OCR text with LLM")

        prompt = self.prompt_manager.get_structure_ocr_text_prompt(ocr_text)
        response = self.provider.generate_text(prompt)

        return self._create_validated_result(
            response.content,
            raw_text=ocr_text,
        ) if response else None

    @staticmethod
    def parse_json_response(content: str) -> Optional[Dict]:
        """Parse JSON response from LLM"""
        try:
            # First, try to parse as-is
            if content.strip().startswith('{'):
                return json.loads(content.strip())

            # Clean markdown JSON blocks
            if '```json' in content:
                start = content.find('```json') + 7
                end = content.find('```', start)
                if end != -1:
                    json_content = content[start:end].strip()
                    return json.loads(json_content)

            # Look for JSON object in the text
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                json_content = json_match.group(0)
                return json.loads(json_content)

            # If all else fails, try to find the last JSON-like structure
            lines = content.split('\n')
            json_lines = []
            in_json = False

            for line in lines:
                if line.strip().startswith('{'):
                    in_json = True
                    json_lines = [line]
                elif in_json:
                    json_lines.append(line)
                    if line.strip().endswith('}') and line.strip().count('}') >= line.strip().count('{'):
                        break

            if json_lines:
                json_content = '\n'.join(json_lines)
                return json.loads(json_content)

            return None

        except json.JSONDecodeError:
            return None

    def _create_validated_result(self, llm_content: str, raw_text: str | None = None) -> Optional[ReceiptAnalysisResult]:
        """Parse LLM response and validate with strict Pydantic validation"""

        # Parse JSON from LLM response
        parsed_data = self.parse_json_response(llm_content)
        if not parsed_data:
            logger.error("Failed to parse JSON from LLM response")
            return None

        # Strict validation - either passes completely or fails
        try:
            return ReceiptAnalysisResult.from_llm_response(
                llm_data=parsed_data,
                raw_text=raw_text
            )

        except ValidationError as e:
            logger.warning(f"Receipt validation failed: {e}")
            return None

        except Exception as e:
            logger.error(f"Unexpected error creating receipt result: {e}")
            return None

    def generate_filter_plan(self, user_query: str) -> Optional[Dict]:
        """Generate query plan from LLM response"""

        logger.info("Generating filter plan with LLM")

        prompt = self.prompt_manager.get_filter_plan_prompt(user_query)
        response = self.provider.generate_text(prompt, max_tokens=1000)

        if not response:
            logger.error("No response from LLM for filter plan")
            return None

        # Parse JSON response
        parsed_plan = self.parse_json_response(response.content)

        if not parsed_plan:
            logger.error("Failed to parse filter plan JSON from LLM")
            return None

        logger.info(f"Generated filter plan: {parsed_plan}")
        return parsed_plan

    def generate_text(self, prompt: str, max_tokens: int = 3000) -> Optional[LLMResponse]:
        """Generate text using the LLM provider"""
        return self.provider.generate_text(prompt, max_tokens)
