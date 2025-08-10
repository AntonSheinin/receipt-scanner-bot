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
- Look for discount/promotion rows (usually with negative values or marked with הנחה, discount, -, etc.)
- Ignore rightmost columns that contain product codes, SKUs, or item numbers
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
            "price": "item price as decimal number (original price as shown on receipt)",
            "quantity": "quantity as integer",
            "category": "food/beverages/household/electronics/clothing/pharmacy/other (if identifiable)",
            "discount": "discount amount as negative decimal number, or 0 if no discount"
        }
    ],
    "total": "total amount as decimal number"
}

Discount handling rules:
- ALWAYS include the "discount" field for every item
- If a discount row appears (typically with negative price or marked as הנחה/discount), associate it with the item above it
- All rows with negative prices should be treated as discounts, it's important to associate them correctly
- Store the discount as it appears on the receipt with negative value
- The item's "price" should be the ORIGINAL price as it appears on the receipt (before discount)
- If no discount exists for an item, set "discount": 0
- If discount cannot be clearly associated with a specific item, set "discount": 0

Column identification rules:
- Focus on columns containing: item names/descriptions, quantities, and prices
- IGNORE columns that appear to contain:
  * Product codes (numeric sequences like 7290000123456)
  * SKUs or barcodes
  * Department codes
  * Item reference numbers
- These code columns are typically on the far right of receipts

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
- The "discount" field is MANDATORY for all items (use 0 if no discount)
- Item prices should reflect the original price shown on receipt, not the discounted price
- Validate that sum of (price * quantity + discount) for all items equals the total"""

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

    @staticmethod
    def get_structure_ocr_text_prompt(ocr_text: str) -> str:
        return f"""You are provided with OCR-extracted text from a receipt. Structure this text into JSON format.

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
            "price": "item price as decimal number (original price as shown)",
            "quantity": "quantity as integer",
            "category": "food/beverages/household/electronics/clothing/pharmacy/other",
            "discount": "discount amount as negative decimal number, or 0 if no discount"
        }}
    ],
    "total": "total amount as decimal number"
}}

Discount handling rules:
- ALWAYS include the "discount" field for every item
- Look for discount lines (marked as הנחה, discount, or showing negative values)
- When a discount line appears, associate it with the item directly above it
- Store discounts as NEGATIVE numbers (e.g., -5.50 for a 5.50 discount)
- The "price" field should show the ORIGINAL price before any discount
- If no discount exists for an item, set "discount": 0
- Ignore discount lines that cannot be clearly associated with an item

Column/Text identification rules:
- Focus on item names, quantities, and prices
- Ignore product codes, SKUs, barcodes (usually long numeric sequences)
- These codes typically appear at the most right side of receipt text

Rules:
- Return ONLY the JSON object, no markdown formatting, no explanations, no additional text
- Use null for missing information
- Preserve Hebrew/non-Latin characters properly
- Ensure prices are valid decimal numbers
- The "discount" field is MANDATORY for all items (use 0 if no discount)
- Item prices should be the original price from receipt, not discounted price
- Detect payment method from text indicators like CASH, CARD, CREDIT, מזומן, אשראי
- Categorize items based on their names and context"""
