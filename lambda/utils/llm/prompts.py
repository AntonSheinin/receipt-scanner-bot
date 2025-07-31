# utils/llm/prompts.py
from datetime import datetime, timezone, timedelta
from typing import Dict
import json

class PromptManager:
    @staticmethod
    def get_receipt_analysis_prompt() -> str:
        # Move RECEIPT_ANALYSIS_PROMPT from config here
        return """Analyze this receipt image carefully and extract structured data..."""
    
    @staticmethod
    def get_query_plan_prompt(question: str) -> str:
        current_date = datetime.now(timezone.utc)
        current_month = current_date.strftime('%Y-%m')
        last_month = (current_date.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
        
        return f"""Analyze this user question about their stored receipts and generate a query plan.

Current date: {current_date.strftime('%Y-%m-%d')}
Current month: {current_month}
Last month: {last_month}

User question: "{question}"

Generate a JSON query plan with this structure - ONLY include fields that are actually needed:
{{
    "filter": {{}},
    "aggregation": "count_receipts",
    "sort_by": "upload_date_desc"
}}

[... rest of existing prompt logic ...]

CRITICAL: Return ONLY the JSON object. Do not include null values or empty arrays."""
    
    @staticmethod
    def get_response_generation_prompt(question: str, results: Dict) -> str:
        return f"""The user asked: "{question}"

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