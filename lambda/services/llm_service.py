from typing import Dict, Optional
from utils.llm.factory import LLMFactory
from utils.llm.prompts import PromptManager
from utils.llm.parsers import ResponseParser

class LLMService:
    def __init__(self, provider_name: str):
        self.provider = LLMFactory.create_provider(provider_name)
        self.prompt_manager = PromptManager()
        self.parser = ResponseParser()
    
    def analyze_receipt(self, image_data: bytes) -> Optional[Dict]:
        """Analyze receipt image"""
        prompt = self.prompt_manager.get_receipt_analysis_prompt()
        response = self.provider.analyze_image(image_data, prompt) 
        
        return self.parser.parse_json_response(response.content) if response else None
    
    def generate_query_plan(self, question: str) -> Optional[Dict]:
        """Generate query plan from natural language"""
        prompt = self.prompt_manager.get_query_plan_prompt(question)
        response = self.provider.generate_text(prompt)
        
        return self.parser.parse_json_response(response.content) if response else None 
    
    def generate_response(self, question: str, results: Dict) -> Optional[str]:
        """Generate human-readable response"""
        prompt = self.prompt_manager.get_response_generation_prompt(question, results)
        response = self.provider.generate_text(prompt)
        
        return response.content if response else None

    def structure_ocr_text(self, ocr_text: str) -> Optional[Dict]:
        """Structure OCR-extracted text using LLM"""
        prompt = f"""You are provided with OCR-extracted text from a receipt. Structure this text into JSON format.

OCR Text:
{ocr_text}

Extract the following information in valid JSON format ONLY:

{{
    "store_name": "name of the store/business",
    "date": "date in YYYY-MM-DD format", 
    "receipt_number": "receipt/transaction number if available",
    "payment_method": "cash|credit_card|other",
    "items": [
        {{
            "name": "item name",
            "price": "item price as decimal number",
            "quantity": "quantity as integer",
            "category": "food/beverages/household/electronics/clothing/pharmacy/other"
        }}
    ],
    "total": "total amount as decimal number"
}}

Rules:
- Return ONLY the JSON object, no markdown formatting
- Use null for missing information
- Preserve Hebrew/non-Latin characters properly
- Ensure prices are valid decimal numbers
- Detect payment method from text indicators like CASH, CARD, CREDIT, מזומן, אשראי
- Categorize items based on their names and context"""

        response = self.provider.generate_text(prompt)
        return self.parser.parse_json_response(response.content) if response else None