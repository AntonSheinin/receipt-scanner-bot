"""
    Prompt Manager module
"""

from datetime import datetime, timezone, timedelta
from typing import Dict
import json
import logging
from config import setup_logging
from providers.category_manager import category_manager


setup_logging()
logger = logging.getLogger(__name__)

class PromptsManager:
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

        taxonomy_json = category_manager.get_taxonomy_json_for_llm()

        return f"""Analyze this ISRAELI receipt image (קבלה or חשבונית מס) carefully and extract structured data. Think through the analysis step-by-step internally:
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

            Available categories/subcategories taxonomy (use subcategory codes for items): {taxonomy_json}

            Extract the following information in valid JSON format ONLY (no additional text or explanations):

            {
                "store_name": "name of the store/business",
                "purchasing_date": "date in YYYY-MM-DD format, always look on CRITICAL DATE PARSING RULES below for correct parsing",
                "receipt_number": "receipt/transaction number if available",
                "payment_method": "cash|credit_card|other",
                "items": [
                    {
                        "name": "item name (preserve Hebrew characters properly)",
                        "price": "item price as decimal number (original price as shown on receipt)",
                        "quantity": "quantity as integer",
                        "subcategory": "subcategory code from the taxonomy json above",
                        "category": "category code of recognized subcategory from the taxonomy json above",
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

            CRITICAL SUBCATEGORY RULES:
            - ALWAYS use the exact subcategory "code" from the taxonomy above
            - ALWAYS fill the category code that corresponds to the subcategory
            - Choose the most specific subcategory that matches the item
            - Choose the category that corresponds to the subcategory
            - For meat items: use "meat_poultry", "frozen_meat_poultry", or "processed_meats_sausages"
            - For dairy: use "dairy_eggs"
            - For bread: use "bread_bakery"
            - For vegetables/fruits: use "fruits_vegetables"
            - For cleaning: use "cleaning_supplies"
            - For fuel/gas: use "fuel_electric"
            - If uncertain, use the most general subcategory within the appropriate main category

            CRITICAL DATE PARSING RULES:
            - Israeli receipts use DD/MM/YYYY or DD/MM/YY format
            - For 2-digit years (YY): ALWAYS assume 20XX (2000s), never 19XX
            - Examples:
            * "14/08/25" = August 14, 2025 (NOT 2014!)
            * "25/12/24" = December 25, 2024
            * "03/01/23" = January 3, 2023
            - ALWAYS output date in YYYY-MM-DD format
            - If unable to determine year definitively, assume current decade (202X)
            - if the recognized year is 2023, that is probably recognition error - change it to 2025
            - carefully check that the final date is valid and correctly formatted

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
    def get_hebrew_structure_ocr_text_prompt(ocr_text: str) -> str:

        taxonomy_json = category_manager.get_taxonomy_json_for_llm()

        return f"""You are provided with OCR-extracted text from an ISRAELI receipt (קבלה). Structure this text into JSON format.
            OCR Text:
            {ocr_text}

            Available categories/subcategories taxonomy (use subcategory codes for items): {taxonomy_json}

            Extract the following information in valid JSON format ONLY:

            {{
                "store_name": "name of the store/business",
                "purchasing_date": "date in YYYY-MM-DD format, always look on CRITICAL DATE PARSING RULES below for correct parsing",
                "receipt_number": "receipt/transaction number if available",
                "payment_method": "cash|credit_card|other",
                "items": [
                    {{
                        "name": "item name",
                        "price": "item price as decimal number (original price as shown)",
                        "quantity": "quantity as integer",
                        "subcategory": "subcategory code from the taxonomy json above",
                        "category": "category code of corresponding subcategory",
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

            CRITICAL SUBCATEGORY RULES:
            - ALWAYS use the exact subcategory "code" from the taxonomy above
            - ALWAYS fill the category code that corresponds to the subcategory
            - Choose the most specific subcategory that matches the item
            - Choose the category that corresponds to the subcategory
            - For meat items: use "meat_poultry", "frozen_meat_poultry", or "processed_meats_sausages"
            - For dairy: use "dairy_eggs"
            - For bread: use "bread_bakery"
            - For vegetables/fruits: use "fruits_vegetables"
            - For cleaning: use "cleaning_supplies"
            - For fuel/gas: use "fuel_electric"
            - If uncertain, use the most general subcategory within the appropriate main category

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
            - if the recognized year is 2023, that is probably recognition error - change it to 2025

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
    def get_filter_plan_prompt(user_query: str) -> str:
        """Generate filtering-only query plan (no sorting or aggregation)"""
        current_date = datetime.now(timezone.utc)
        current_month = current_date.strftime('%Y-%m')
        last_month = (current_date.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')

        taxonomy_json = category_manager.get_taxonomy_json_for_llm()

        return f"""Analyze this user question about their stored receipts and generate a FILTERING plan only.
            IMPORTANT: All receipts are Israeli receipts with Hebrew text. When generating item_keywords,
            ALWAYS use Hebrew keywords regardless of the question language.

            Current date: {current_date.strftime('%Y-%m-%d')}
            Current month: {current_month}
            Last month: {last_month}

            Available categories/subcategories codes taxonomy: {taxonomy_json}

            User question: "{user_query}"

            Generate a JSON filtering plan with this structure - ONLY include fields that are actually needed for filtering:
            {{
                "filter": {{}}
            }}

            Available filter fields (only include if relevant):
            - "item_keywords": ["keyword1", "keyword2"] - MUST be in Hebrew since receipts are Hebrew, if user wants to filter by item names only
            - "categories": ["category"] - main categories codes from taxonomy
            - "subcategories": ["subcategory"] - specific subcategories codes from taxonomy
            - "date_range": {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}}
            - "store_names": ["store1", "store2"]
            - "price_range": {{"min": 10, "max": 100}}
            - "payment_methods": ["cash", "credit_card", "other"]
            - "limit": 50

            Rules:
            - Use "subcategories" codes for specific items (like "meat_poultry", "dairy_eggs")
            - Use "categories" codes for broader queries (like "food", "household")
            - DO NOT include fields with null values - omit them completely
            - DO NOT include empty arrays - omit them completely
            - Only set limit when you want to restrict results (10-100)
            - NO SORTING - the LLM will handle any sorting/ordering in the response

            CRITICAL: Return keywords in Hebrew characters only if user wants to filter by item names only. Don't include
            keywords at all if user want to filter by category or subcategory. Only include keywords with category and/or subcategory
            if user want to filter both all category/subcategory items with certain items.

            For example:
            - If user wants to filter by item names: "חלב", "לחם" - include keywords "חלב", "לחם"
            - If user wants to filter by category: "מזון" - include category "מזון" only without keywords
            - If user wants to filter by subcategory: "חלב ומוצרי חלב" - include subcategory "חלב ומוצרי חלב" only without keywords
            - if user wants to filter by both category and item names: "מזון", "מרכך" - include category "מזון" and keywords "מרכך"

            CRITICAL: Return ONLY the JSON object. No explanations or comments.
        """

    @staticmethod
    def get_receipt_analysis_response_prompt(question: str, receipt_data: Dict) -> str:
        """Generate natural language response from filtered receipt data"""

        receipts_json = json.dumps(receipt_data, indent=2, ensure_ascii=False)

        return f"""The user asked: "{question}"
            Here is the filtered receipt data that matches their query:

            {receipts_json}

            Analyze this data and provide a helpful, conversational response in Hebrew. Requirements:

            1. **Answer the user's question directly and accurately**
            2. **Perform any necessary calculations** (sums, averages, comparisons, etc.)
            3. **Use emojis and formatting** for better readability
            4. **Be conversational and helpful**, not robotic
            5. **Include specific numbers and insights** from the data
            6. **If no relevant data found**, explain why and suggest alternatives
            7. **For comparisons**, highlight the best deals or interesting patterns
            8. **For spending analysis**, provide useful insights and trends

            Mathematical Operations You Can Perform:
            - Sum totals across receipts
            - Calculate averages
            - Find min/max values
            - Count items/receipts
            - Group by store/category/date
            - Calculate percentages
            - Compare prices across stores
            - Analyze spending patterns

            Response Guidelines:
            - Write in Hebrew when appropriate for Israeli users
            - Use **bold** text for important numbers
            - Include relevant emojis (💰 for money, 🏪 for stores, 📅 for dates, etc.)
            - Keep response concise but informative (max 4096 characters)
            - Format large numbers clearly (use ₪ for Israeli Shekels)
            - If calculations don't make sense, explain why

            Example response style:
            "🏪 **מצאתי 15 קבלות מרמי לוי**

            💰 **סה״כ הוצאה**: ₪1,247.50
            📊 **הוצאה ממוצעת לקבלה**: ₪83.17
            📅 **תקופה**: 01/08/2024 - 15/08/2024

            🥛 **חלב הכי זול**: ₪4.90 ברמי לוי (12/08)
            🥛 **חלב הכי יקר**: ₪6.20 בשופרסל (08/08)

            💡 **מסקנה**: רמי לוי חוסך לך ₪1.30 על כל קנית חלב!"

            Now analyze the receipt data and answer the user's question."""

    @staticmethod
    def get_stitching_analysis_prompt() -> str:
        """
            System prompt: detect the FULL duplicated band (all overlapping rows) between
            the bottom of the first image (top part) and the top of the second image (bottom part),
            and output the stitching plan JSON using the exact schema below.
        """
        return (
            "You are an expert vision model analyzing two photos of the same store receipt.\n"
            "The first image is ALWAYS the top part, the second image is the bottom part.\n"
            "Your goal is to create a stitching plan that removes the ENTIRE duplicated band at the start of the second image.\n\n"

            "Respond ONLY in JSON following this exact schema:\n"
            "{\n"
            "  \"top_rotate_deg\": 0 | 90 | 180 | 270,\n"
            "  \"bottom_rotate_deg\": 0 | 90 | 180 | 270,\n"
            "  \"crop_pixels_from_top\": number,\n"
            "  \"background_threshold\": number | null,\n"
            "  \"enhance_contrast\": number,\n"
            "  \"enhance_brightness\": number\n"
            "}\n\n"

            "Field semantics and guidance:\n"
            "- top_rotate_deg / bottom_rotate_deg: Use only 0/90/180/270. Prefer 0 if text is upright and readable.\n"
            "- crop_pixels_from_top: NON-NEGATIVE integer pixels to trim from the TOP of the SECOND image to remove the FULL duplicated band (ALL overlapping rows) that also appears at the BOTTOM of the first image.\n"
            "  • Detect multiple matching lines, not just a single line.\n"
            "  • Expand the band until the first line of NEW content on the second image (do not leave any duplicate row).\n"
            "  • Typical receipts have overlaps in the ~120–320 px range, but use the actual visual evidence.\n"
            "- background_threshold: If the sheet/background separation is clearly a single light threshold, return a grayscale threshold in [160..255]; otherwise return null (auto-bbox will handle it).\n"
            "- enhance_contrast: Mild multiplier in [1.0..3.0] (often 1.2–1.8).\n"
            "- enhance_brightness: Mild multiplier in [0.8..2.0] (often 1.0–1.2).\n\n"

            "How to detect the FULL overlap robustly:\n"
            "1) Normalize widths if necessary (conceptually align columns). Compare in grayscale.\n"
            "2) Use MULTI-ANCHOR matching: identify at least TWO distinct matching horizontal rows (e.g., item lines, separators) at the bottom of image 1 and the top of image 2 with consistent vertical spacing.\n"
            "3) Sweep candidate band heights K over a practical range (e.g., 50..400 px depending on scale). For each K, compare LAST K rows of image 1 with FIRST K rows of image 2.\n"
            "5) EXPAND the matched band upward/downward to include ALL consecutive duplicated rows until the first line that diverges (the first NEW row on image 2).\n"
            "6) Sanity check at the crop boundary: the first visible row AFTER cropping on image 2 must NOT appear at the end of image 1 (no partial duplicates cut).\n"
            "7) If the match is uncertain or extremely short, set crop_pixels_from_top = 0.\n\n"

            "Bias and validation:\n"
            "- Ensure rotations remain one of {0,90,180,270}; do not invent other angles.\n"
            "- Keep enhancement values conservative to avoid artifacts.\n\n"

            "Formatting rules:\n"
            "- Return only the JSON object matching the schema above.\n"
            "- Do not add comments, markdown, trailing commas, or extra keys.\n"
            "- Use numbers (not strings) for numeric fields.\n"
        )
