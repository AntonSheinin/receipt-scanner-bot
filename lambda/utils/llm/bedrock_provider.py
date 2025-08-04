from typing import Optional, List, Dict, Any
import json
import base64
import logging
from utils.llm.interfaces import LLMProvider, LLMResponse
from config import get_bedrock_client, BEDROCK_MODEL_ID, setup_logging

setup_logging()
logger = logging.getLogger(__name__)

class BedrockProvider(LLMProvider):
    def __init__(self):
        self.client = get_bedrock_client()
        self.model_id = BEDROCK_MODEL_ID
    
    def _invoke_model(self, messages: List[Dict[str, Any]], max_tokens: int) -> Optional[LLMResponse]:
        """Common Bedrock API invocation logic"""
        try:
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "messages": messages
            }
            
            response = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body),
                contentType="application/json"
            )
            
            response_body = json.loads(response['body'].read())
            if 'content' in response_body and response_body['content']:
                content = response_body['content'][0]['text']
                usage = response_body.get('usage', {}).get('output_tokens')
                return LLMResponse(content=content, usage_tokens=usage)
            
            return None
        except Exception as e:
            print(f"Bedrock API error: {e}")
            return None
    
    def generate_text(self, prompt: str, max_tokens: int = 1000) -> Optional[LLMResponse]:
        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": prompt}]
        }]
        return self._invoke_model(messages, max_tokens)
    
    def analyze_image(self, image_data: bytes, prompt: str, max_tokens: int = 2000) -> Optional[LLMResponse]:
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        messages = [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_base64}},
                {"type": "text", "text": prompt}
            ]
        }]
        return self._invoke_model(messages, max_tokens)