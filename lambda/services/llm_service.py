import re
from typing import Dict, Optional
import logging
import json
from config import setup_logging
from provider_factory import ProviderFactory
from utils.llm.prompts import PromptManager

setup_logging()
logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self, provider_name: str):
        self.provider = ProviderFactory.create_llm_provider(provider_name)
        self.prompt_manager = PromptManager()

    def analyze_receipt(self, image_data: bytes) -> Optional[Dict]:
        """Analyze receipt image"""

        logger.info("Analyzing receipt image with LLM")

        prompt = self.prompt_manager.get_receipt_analysis_prompt()
        response = self.provider.analyze_image(image_data, prompt)

        logger.info(f"LLM response: {response.content if response else 'No response'}")

        return self.parse_json_response(response.content) if response else None

    def generate_query_plan(self, question: str) -> Optional[Dict]:
        """Generate query plan from natural language"""

        logger.info(f"Generating query plan for question: {question}")

        prompt = self.prompt_manager.get_query_plan_prompt(question)
        response = self.provider.generate_text(prompt)

        logger.info(f"LLM query plan response: {response.content if response else 'No response'}")

        return self.parse_json_response(response.content) if response else None

    def generate_response(self, question: str, results: Dict) -> Optional[str]:
        """Generate human-readable response"""

        logger.info(f"Generating response for question: {question} with results: {results}")

        prompt = self.prompt_manager.get_response_generation_prompt(question, results)
        response = self.provider.generate_text(prompt)

        logger.info(f"LLM response: {response.content if response else 'No response'}")

        return response.content if response else None

    def structure_ocr_text(self, ocr_text: str) -> Optional[Dict]:
        """Structure OCR-extracted text using LLM"""

        logger.info("Structuring OCR text with LLM")

        prompt = self.prompt_manager.get_structure_ocr_text_prompt(ocr_text)
        response = self.provider.generate_text(prompt)

        logger.info(f"LLM structured OCR response: {response.content if response else 'No response'}")

        return self.parse_json_response(response.content) if response else None

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
