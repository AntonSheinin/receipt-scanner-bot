# services/llm_service.py
from typing import Dict, Optional
from utils.llm.factory import LLMFactory
from utils.llm.prompts import PromptManager
from utils.llm.parsers import ResponseParser

class LLMService:
    def __init__(self, provider_name: str = 'bedrock'):
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