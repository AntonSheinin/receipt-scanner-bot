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

CRITICAL DATE PARSING RULES:
- Israeli receipts use DD/MM/YYYY or DD/MM/YY format
- For 2-digit years (YY): ALWAYS assume 20XX (2000s), never 19XX
- Examples:
  * "14/08/25" = August 14, 2025 (NOT 2014!)
  * "25/12/24" = December 25, 2024
  * "03/01/23" = January 3, 2023
- ALWAYS output date in YYYY-MM-DD format
- If date is ambiguous, use context clues (receipt freshness, other dates on receipt)
- If unable to determine year definitively, assume current decade (202X)

CRITICAL ITEM PARSING RULES:
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
- Israeli phone numbers format: 03-1234567, 052-1234567
- Prices may include ₪ symbol or ש"ח abbreviation
- The "discount" field is MANDATORY for all items (use 0 if no discount)
- Item prices should reflect the original price shown on receipt, not the discounted price
- Validate that sum of (price * quantity + discount) for all items equals the total

CRITICAL REQUIRED FIELDS (must never be null/empty):
- store_name: The business name (Hebrew or English text)
- date: Receipt date (within last 6 months)
- payment_method: Must be exactly "cash", "credit_card", or "other"
- total: Total amount as positive decimal number

Items array can be empty for simple receipts without item breakdown.
If any required field is missing or invalid, the analysis fails completely.

Return ONLY valid JSON with all required fields, no explanations.

"""

    @staticmethod
    def get_query_plan_prompt(question: str) -> str:
        current_date = datetime.now(timezone.utc)
        current_month = current_date.strftime('%Y-%m')
        last_month = (current_date.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')

        return f"""Analyze this user question about their stored receipts and generate a query plan.

IMPORTANT: All receipts are Israeli receipts with Hebrew text. When generating item_keywords,
ALWAYS use Hebrew keywords regardless of the question language.

Current date: {current_date.strftime('%Y-%m-%d')}
Current month: {current_month}
Last month: {last_month}

User question: "{question}"

Available filter fields (only include if relevant):
- "item_keywords": ["keyword1", "keyword2"] - MUST be in Hebrew since receipts are Hebrew

Generate a JSON query plan with this structure - ONLY include fields that are actually needed:
{{
    "filter": {{}},
    "aggregation": "count_receipts",
    "sort_by": "upload_date_desc"
}}

[... rest of existing prompt logic ...]

CRITICAL: Return keywords in Hebrew characters, not Russian or English.

Examples (but not all the possible Hebrew keywords):
- For alcohol: ["אלכוהול", "משקאות חריפים", "יין", "בירה", "ויסקי", "וודקה", "ברנדי"]
- For food: ["לחם", "חלב", "בשר", "ירקות"]
- For household: ["סבון", "חומרי ניקוי", "נייר טואלט"]

CRITICAL: Return ONLY the JSON object. Do not include null values or empty arrays.
Don't include any explanations or comments.
"""

    @staticmethod
    def get_response_generation_prompt(question: str, results: Dict) -> str:
        return f"""The user asked: "{question}"

Query executed: {json.dumps(results.get('query', {}), indent=2)}

Aggregation results: {json.dumps(results.get('results', {}), indent=2)}

Total receipts found: {results.get('total_receipts', 0)}

Raw receipts data for context: {json.dumps(results.get('raw_data', []), indent=2)}

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

CRITICAL DATE PARSING RULES:
- Israeli receipts use DD/MM/YYYY or DD/MM/YY format
- For 2-digit years (YY): ALWAYS assume 20XX (2000s), never 19XX
- Examples:
  * "14/08/25" = August 14, 2025 (NOT 2014!)
  * "25/12/24" = December 25, 2024
  * "03/01/23" = January 3, 2023
- ALWAYS output date in YYYY-MM-DD format
- If date is ambiguous, use context clues (receipt freshness, other dates on receipt)
- If unable to determine year definitively, assume current decade (202X)

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
- Validate that sum of (price * quantity + discount) for all items approximates the total

CRITICAL REQUIRED FIELDS (must never be null/empty):
- store_name: The business name (Hebrew or English text)
- date: Receipt date (within last 6 months)
- payment_method: Must be exactly "cash", "credit_card", or "other"
- total: Total amount as positive decimal number

Items array can be empty for simple receipts without item breakdown.
If any required field is missing or invalid, the analysis fails completely.

Return ONLY valid JSON with all required fields, no explanations.
"""

    @staticmethod
    def get_generate_query_plan_prompt(question: str):
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

Available filter fields (only include if relevant):
- "date_range": {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}}
- "store_names": ["store1", "store2"]
- "item_keywords": ["keyword1", "keyword2"]
- "categories": ["food", "beverages", "household"]
- "price_range": {{"min": 10, "max": 100}}
- "payment_methods": ["cash", "credit_card", "other"]
- "limit": 1

Available aggregations:
- "sum_total" - total spending
- "sum_by_category" - spending by category
- "min_price_by_store" - cheapest price by store
- "max_price_by_store" - most expensive price by store
- "count_receipts" - count receipts (use for "show me" queries)

Available sort options:
- "upload_date_desc" - most recently uploaded first
- "upload_date_asc" - oldest uploaded first
- "receipt_date_desc" - most recent purchase date first
- "receipt_date_asc" - oldest purchase date first
- "total_desc" - highest amount first
- "total_asc" - lowest amount first

Rules:
- For "latest/last uploaded" queries, use sort_by: "upload_date_desc"
- For "most recent purchase" queries, use sort_by: "receipt_date_desc"
- For "show me" or "what is" queries, use aggregation: "count_receipts"
- DO NOT include fields with null values - omit them completely
- DO NOT include empty arrays - omit them completely
- Only set limit when you want to restrict results (1-10)

Examples:
"Last receipt by upload date" → {{"filter": {{"limit": 1}}, "aggregation": "count_receipts", "sort_by": "upload_date_desc"}}
"How much did I spend on food?" → {{"filter": {{"categories": ["food"]}}, "aggregation": "sum_by_category"}}
"Show my 3 biggest purchases" → {{"filter": {{"limit": 3}}, "aggregation": "count_receipts", "sort_by": "total_desc"}}

CRITICAL: Return ONLY the JSON object. Do not include null values or empty arrays. Only include relevant fields."""
