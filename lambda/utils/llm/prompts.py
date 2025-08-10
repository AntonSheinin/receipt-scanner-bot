from datetime import datetime, timezone, timedelta
from typing import Dict
import json

class PromptManager:
    def __init__(self, locale: str = "he_IL"):
        self.locale = locale

    def get_receipt_analysis_prompt(self) -> str:
        """
        Generate the prompt for receipt analysis using LLM.
        Enhanced for Israeli/Hebrew receipts.
        """
        if self.locale == "he_IL":
            return self.get_hebrew_receipt_analysis_prompt()
        else:
            raise ValueError(f"Unsupported locale: {self.locale}")

    def get_structure_ocr_text_prompt(self, ocr_text: str) -> str:
        """
        Generate the prompt for structuring OCR text using LLM.
        Enhanced for Israeli/Hebrew receipts.
        """
        if self.locale == "he_IL":
            return self.get_hebrew_structure_ocr_text_prompt(ocr_text)
        else:
            raise ValueError(f"Unsupported locale: {self.locale}")

    @staticmethod
    def get_hebrew_receipt_analysis_prompt() -> str:
        """
        Generate the prompt for receipt analysis using LLM.
        Enhanced for Israeli/Hebrew receipts.
        """
        return """Analyze this ISRAELI receipt image (קבלה or חשבונית מס) carefully and extract structured data. Think through the analysis step-by-step internally:

- First examine the overall layout - Israeli receipts typically have Hebrew text right-to-left
- Locate and read all text sections methodically
- Identify item names (שם פריט), prices (מחיר), quantities (כמות), and categories
- Look for discount/promotion rows marked with: הנחה, מבצע, discount, -, or negative values
- Ignore rightmost columns that contain product codes (ברקוד), SKUs (מק"ט), or item numbers
- Look for payment method indicators: מזומן, אשראי, CASH, CARD, CREDIT, VISA, MASTERCARD, ויזה, מאסטרקארד, ישראכרט
- Common Israeli chains: רמי לוי, שופרסל, ויקטורי, עושר עד, יינות ביתן, טיב טעם, AM:PM, סופר פארם etc.
- Validate that extracted prices are reasonable and properly formatted (₪ symbol may appear)
- Cross-reference individual items with the total amount (סה"כ, סיכום, total)
- Preserve Hebrew text properly without escaping to Unicode

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

Israeli Receipt Specific Rules:
- Hebrew text reading: right-to-left
- Common discount terms: הנחה, מבצע, הנחת כמות, הנחת חבר מועדון
- VAT/Tax line (מע"מ): This is NOT an item, skip it
- Deposit lines (פיקדון): Include as separate items with "deposit" category
- Common quantity abbreviations: יח' (units), ק"ג (kg), גרם (grams), ליטר (liter)
- Store loyalty cards: מועדון, חבר מועדון, כרטיס אשראי מועדון
- Receipt types: חשבונית מס (tax invoice), קבלה (receipt), חשבונית מס קבלה

CRITICAL ITEM PARSING RULE:
- Lines starting with a number (product code/barcode) mark the START of a new item
- All following lines WITHOUT a leading number belong to that item:
  * Weight/quantity measurements (e.g., "0.724" = actual weight in kg)
  * Price calculations (e.g., "36.13" = total price)
  * Discount amounts (הנחה, negative values)
- Example pattern:
  * "4043041000457 חזה עוף נקניק רודוס 49.90" → Item with unit price 49.90/kg
  * "0.724" → Actual weight purchased
  * "36.13" → Calculated price (0.724 × 49.90)
  * Extract: name="חזה עוף נקניק רודוס", price=49.90, quantity=0.724
  * System will calculate: 49.90 × 0.724 = 36.13

Column identification rules:
- Focus on columns containing: item names/descriptions, quantities, prices and discounts
- IGNORE columns that appear to contain:
  * Product codes (ברקוד) - numeric sequences like 7290000123456
  * SKUs (מק"ט) or barcodes
  * Department codes (קוד מחלקה)
  * Item reference numbers (מספר פריט, מספר מוצר, קוד מוצר)
- These code columns are typically on the far right of receipts or in the middle columns

Discount handling rules:
- ALWAYS include the "discount" field for every item
- Israeli receipts often show: הנחה, הנחת מבצע, or negative amounts below items
- All rows with negative prices should be treated as discounts
- Store the discount as it appears on receipt with negative value
- The item's "price" should be the ORIGINAL price as shown (before discount)
- If no discount exists for an item, set "discount": 0

Payment method detection rules:
- "cash" for: מזומן, CASH, מזומנים
- "credit_card" for: אשראי, כרטיס אשראי, CREDIT, VISA, ויזה, מאסטרקארד, ישראכרט, MASTERCARD, אמקס, American Express
- "other" for: שיק (check), העברה בנקאית (bank transfer), ביט (Bit app)
- Use null if payment method cannot be determined

Important:
- Return ONLY the JSON object, no markdown formatting or explanations or comments
- Israeli phone numbers format: 03-1234567, 052-1234567
- Israeli dates may appear as: DD/MM/YYYY or DD.MM.YYYY
- Prices may include ₪ symbol or ש"ח abbreviation
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
    def get_hebrew_structure_ocr_text_prompt(ocr_text: str) -> str:
        return f"""You are provided with OCR-extracted text from an ISRAELI receipt (קבלה). Structure this text into JSON format.

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

Israeli Receipt Specific Patterns:
- Store names: רמי לוי, שופרסל, ויקטורי, עושר עד, יינות ביתן, טיב טעם, AM:PM, סופר פארם etc.
- Total indicators: סה"כ, סיכום, סך הכל, לתשלום, TOTAL
- VAT/Tax (מע"מ): Skip this line - it's not an item
- Deposit (פיקדון): Include as separate item with "deposit" category
- Quantity units: יח', ק"ג, גרם, ליטר, מ"ל
- Date formats: DD/MM/YYYY, DD.MM.YYYY, DD-MM-YYYY

CRITICAL ITEM PARSING RULE:
- Lines starting with a number (product code/barcode) mark the START of a new item
- All following lines WITHOUT a leading number belong to that item:
  * Weight/quantity measurements (e.g., "0.724" = actual weight in kg)
  * Price calculations (e.g., "36.13" = total price)
  * Discount amounts (הנחה, negative values)
- Example pattern:
  * "4043041000457 חזה עוף נקניק רודוס 49.90" → Item with unit price 49.90/kg
  * "0.724" → Actual weight purchased
  * "36.13" → Calculated price (0.724 × 49.90)
  * Extract: name="חזה עוף נקניק רודוס", price=49.90, quantity=0.724
  * System will calculate: 49.90 × 0.724 = 36.13

Discount handling rules:
- ALWAYS include the "discount" field for every item
- Look for discount lines: הנחה, הנחת מבצע, מבצע, הנחת כמות, הנחת חבר מועדון, discount, - (negative values)
- When a discount line appears, associate it with the item directly above it
- Store discounts as NEGATIVE numbers (e.g., -5.50 for a 5.50 discount)
- The "price" field should show the ORIGINAL price before any discount
- If no discount exists for an item, set "discount": 0
- Ignore discount lines that cannot be clearly associated with an item

Column/Text identification rules:
- Focus on item names, quantities, and prices
- IGNORE product codes, SKUs (מק"ט), barcodes (ברקוד) - usually long numeric sequences
- Israeli barcodes often start with 729
- These codes typically appear at the rightmost side of receipt text
- Skip lines with only numbers like: 7290000123456, 12345678

Payment method detection rules:
- "cash" for: מזומן, CASH, מזומנים, נתקבל מזומן
- "credit_card" for: אשראי, כרטיס אשראי, כ.אשראי, CREDIT, VISA, ויזה, מאסטרקארד, ישראכרט, MASTERCARD, אמריקן אקספרס
- "other" for: שיק, המחאה, העברה בנקאית, ביט (Bit), פייבוקס (PayBox), פייפאל (PayPal)
- Use null if payment method cannot be determined

Rules:
- Return ONLY the JSON object, no markdown formatting, no explanations, no additional text
- Use null for missing information
- Preserve Hebrew/non-Latin characters properly
- Ensure prices are valid decimal numbers
- The "discount" field is MANDATORY for all items (use 0 if no discount)
- Item prices should be the original price from receipt, not discounted price
- Categorize items based on their names and context
- Hebrew text may appear reversed or broken in OCR - try to reconstruct meaningful item names
- Remove any Unicode escape sequences (\\u05xx) - use actual Hebrew characters
- Validate that sum of (price * quantity + discount) for all items approximates the total"""
