"""
LLM Client - Bedrock/Claude Interactions
"""
import json
import logging
import base64
from typing import Dict, Optional

from config import get_bedrock_client, BEDROCK_MODEL_ID, RECEIPT_ANALYSIS_PROMPT, setup_logging


setup_logging()
logger = logging.getLogger(__name__)

class LLMClient:
    """Client for LLM interactions"""
    
    def __init__(self):
        self.bedrock_client = get_bedrock_client()
    
    def analyze_receipt(self, image_data: bytes) -> Optional[Dict]:
        """Analyze receipt using Bedrock Claude Vision"""
        try:
            image_base64 = base64.b64encode(image_data).decode('utf-8')
            
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2000,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_base64}},
                        {"type": "text", "text": RECEIPT_ANALYSIS_PROMPT}
                    ]
                }]
            }
            
            response = self.bedrock_client.invoke_model(
                modelId=BEDROCK_MODEL_ID,
                body=json.dumps(request_body),
                contentType="application/json"
            )
            
            response_body = json.loads(response['body'].read())
            
            if 'content' in response_body and response_body['content']:
                content = response_body['content'][0]['text'].strip()
                return self._parse_json_response(content)
            
            return None
            
        except Exception as e:
            logger.error(f"Receipt analysis error: {e}")
            return None
    
    def generate_query_plan(self, prompt: str) -> Optional[Dict]:
        """Generate query plan using LLM"""

        try:
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
            }

            response = self.bedrock_client.invoke_model(
                modelId=BEDROCK_MODEL_ID,
                body=json.dumps(request_body),
                contentType="application/json"
            )
            
            response_body = json.loads(response['body'].read())
            
            if 'content' in response_body and response_body['content']:
                content = response_body['content'][0]['text'].strip()
                return self._parse_json_response(content)
            
            return None
            
        except Exception as e:
            logger.error(f"Query plan generation error: {e}")
            return None
    
    def generate_response(self, question: str, results: Dict) -> Optional[str]:
        """Generate human-readable response using LLM"""
        try:
            prompt = f"""The user asked: "{question}"

Query executed: {json.dumps(results.get('query', {}), indent=2)}

Aggregation results: {json.dumps(results.get('results', {}), indent=2)}

Total receipts found: {results.get('total_receipts', 0)}

Sample receipt data for context: {json.dumps(results.get('raw_data', []), indent=2)}

Generate a helpful, conversational response for Telegram. Requirements:
1. Answer the user's question directly and clearly
2. Include relevant numbers and insights
3. Use emojis and markdown formatting for Telegram
4. Be conversational and helpful, not robotic
5. If no results found, explain why and suggest alternatives
6. For price comparisons, highlight the best deal
7. For spending analysis, provide useful insights

Format for Telegram with **bold** text and emojis. Keep it concise but informative."""

            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
            }
            
            response = self.bedrock_client.invoke_model(
                modelId=BEDROCK_MODEL_ID,
                body=json.dumps(request_body),
                contentType="application/json"
            )
            
            response_body = json.loads(response['body'].read())
            
            if 'content' in response_body and response_body['content']:
                return response_body['content'][0]['text'].strip()
            
            return None
            
        except Exception as e:
            logger.error(f"Response generation error: {e}")
            return None
    
    def _parse_json_response(self, content: str) -> Optional[Dict]:
        """Parse JSON response from LLM"""
        try:
            # First, try to parse as-is
            if content.strip().startswith('{'):
                return json.loads(content.strip())
            
            # Clean markdown JSON blocks
            if '```json' in content:
                # Extract content between ```json and ```
                start = content.find('```json') + 7
                end = content.find('```', start)
                if end != -1:
                    json_content = content[start:end].strip()
                    return json.loads(json_content)
            
            # Look for JSON object in the text
            import re
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
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {content}")
            return None