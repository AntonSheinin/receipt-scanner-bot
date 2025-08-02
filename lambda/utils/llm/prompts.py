from datetime import datetime, timezone, timedelta
from typing import Dict
import json

class PromptManager:
    @staticmethod
    def get_receipt_analysis_prompt() -> str:
        """
            Generate the prompt for receipt analysis using LLM.
        """

        return """Analyze this receipt image carefully and extract structured data. Think through the analysis step-by-step internally:

- First examine the overall layout and identify languages used
- Locate and read all text sections methodically 
- Identify item names, prices, quantities, and categories
- Look for payment method indicators (CASH, CARD, CREDIT, VISA, MASTERCARD, מזומן, אשראי etc.)
- Validate that extracted prices are reasonable and properly formatted
- Cross-reference individual items with the total amount
- Preserve Hebrew/non-Latin text properly without escaping to Unicode

Extract the following information in valid JSON format ONLY (no additional text or explanations):

{
    "store_name": "name of the store/business",
    "date": "date in YYYY-MM-DD format",
    "receipt_number": "receipt/transaction number if available",
    "payment_method": "cash|credit_card|other",
    "items": [
        {
            "name": "item name (preserve Hebrew characters properly)",
            "price": "item price as decimal number",
            "quantity": "quantity as integer", 
            "category": "food/beverages/household/electronics/clothing/pharmacy/other (if identifiable)"
        }
    ],
    "total": "total amount as decimal number"
}

Payment method detection rules:
- Look for text indicators like: CASH, CARD, CREDIT, VISA, MASTERCARD, מזומן, אשראי etc.
- "cash" for cash payments or text containing "CASH", "מזומן"
- "credit_card" for card payments or text containing "CARD", "CREDIT", "VISA", "MASTERCARD", "כרטיס", "אשראי"
- "other" for any other payment method
- Use null if payment method cannot be determined

Important:
- Return ONLY the JSON object, no markdown formatting or explanations
- If information is not clearly visible, use null
- Ensure all prices are valid decimal numbers
- Preserve Hebrew and special characters correctly
- Categorize items accurately based on context and name
- Validate that individual item prices logically add up to the total"""
    
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