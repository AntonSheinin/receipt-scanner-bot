import json
import re
from typing import Optional, Dict

class ResponseParser:
    @staticmethod
    def parse_json_response(content: str) -> Optional[Dict]:
        """Parse JSON response from LLM - moved from LLMClient"""
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