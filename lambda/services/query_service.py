"""
    Query Processing Service module
"""

import json
import logging
from typing import Dict, Optional, List, Any
from config import LLM_PROVIDER, setup_logging
from services.telegram_service import TelegramService
from services.storage_service import StorageService
from services.llm_service import LLMService
from utils.helpers import create_response, get_secure_user_id
from utils.llm.prompts import PromptManager


setup_logging()
logger = logging.getLogger(__name__)

class QueryService:
    """Service for natural language query processing - simplified approach"""

    def __init__(self):
        self.telegram = TelegramService()
        self.storage = StorageService()
        self.llm = LLMService(LLM_PROVIDER)
        self.prompts = PromptManager()

    def process_query(self, question: str, chat_id: int) -> Dict:
        """Handle natural language queries in 3 simplified steps"""

        logger.info(f"Processing query: {question}")

        secure_user_id = get_secure_user_id(chat_id)

        try:
            self.telegram.send_typing(chat_id)
            self.telegram.send_message(chat_id, "🔍 מנתחים את שאלתך...")

            # Step 1: Generate filter-only query plan
            query_plan = self._generate_filter_plan(question)
            if not query_plan:
                self.telegram.send_message(chat_id, "❌ לא הצלחנו להבין את שאלתך. נסה לנסח מחדש.")
                logger.error(f"Failed to generate query plan for question: {question}")
                return create_response(200, {"status": "failed"})

            logger.info(f"Filter plan for '{question}': {json.dumps(query_plan, indent=2)}")

            # Step 2: Get filtered receipts
            filtered_receipts = self._get_filtered_receipts(query_plan, secure_user_id)
            if not filtered_receipts:
                self.telegram.send_message(chat_id, "❌ לא נמצאו נתונים תואמים!")
                logger.info("No matching data found for query")
                return create_response(200, {"status": "no_data"})

            logger.info(f"Found {len(filtered_receipts)} filtered receipts")

            # Step 3: Let LLM analyze and respond
            self.telegram.send_message(chat_id, "💭 מכינים את התשובה...")
            response = self._generate_llm_response(question, filtered_receipts)

            logger.info(f"LLM response generated successfully")

            # Step 4: Send to user
            if response:
                self.telegram.send_message(chat_id, response)
                logger.info("Response sent successfully")
            else:
                self.telegram.send_message(chat_id, "❌ הייתה בעיה ביצירת התשובה. נסה לנסח מחדש.")
                logger.error("Failed to generate response from LLM")

            return create_response(200, {"status": "completed"})

        except Exception as e:
            logger.error(f"Query error: {e}", exc_info=True)
            self.telegram.send_message(chat_id, "❌ הייתה בעיה בעיבוד שאלתך.")
            return create_response(200, {"status": "error"})

    def _generate_filter_plan(self, user_query: str) -> Optional[Dict]:
        """Generate filtering-only query plan using LLM"""

        try:
            filter_plan = self.llm.generate_filter_plan(user_query)

        except Exception as e:
            logger.error(f"Filter plan error: {e}")
            return None

        try:
            filter_plan = self._validate_filter_plan(filter_plan)
            logger.info(f"Cleaned filter plan: {json.dumps(filter_plan, indent=2)}")

        except Exception as e:
            logger.error(f"Filter plan validation error: {e}")
            return None

        return filter_plan

    def _get_filtered_receipts(self, query_plan: Dict, user_id: str) -> List[Dict[str, Any]]:
        """Get and filter receipts - simplified version without sorting"""

        # Get filtered receipts from storage
        receipts = self.storage.get_filtered_receipts(query_plan, user_id)
        if not receipts:
            return []

        logger.info(f"Found {len(receipts)} receipts from storage")

        try:
            # Apply item-level filtering
            filtered_receipts = self._filter_by_items(receipts, query_plan.get("filter", {}))
            logger.info(f"After item filtering: {len(filtered_receipts)} receipts")

        except Exception as e:
            logger.error(f"Item filtering error: {e}")
            return receipts

        # Apply limit
        receipts_limit = query_plan.get("filter", {}).get("limit")
        if receipts_limit and isinstance(receipts_limit, int) and receipts_limit > 0:
            filtered_receipts = filtered_receipts[:receipts_limit]
            logger.info(f"After limit {receipts_limit}: {len(filtered_receipts)} receipts")

        return filtered_receipts

    def _generate_llm_response(self, user_query: str, receipts: List[Dict[str, Any]]) -> Optional[str]:
        """Generate response using LLM with filtered receipts data"""

        # Prepare receipt data for LLM
        receipt_data = {
            "total_receipts": len(receipts),
            "receipts": receipts
        }

        prompt = self.prompts.get_receipt_analysis_response_prompt(user_query, receipt_data)

        try:
            response = self.llm.generate_text(prompt, max_tokens=2000)
            return response.content if response else None

        except Exception as e:
            logger.error(f"LLM response generation error: {e}")
            return None

    def _validate_filter_plan(self, query_plan: Dict) -> Dict:
        """Clean and validate filter plan - no sorting needed"""

        # Clean up filter
        clean_filter = {}
        filter_params = query_plan.get("filter", {})

        # Only include non-null, non-empty values
        for key, value in filter_params.items():
            if value is not None:
                if isinstance(value, list) and len(value) > 0:
                    clean_filter[key] = value
                elif isinstance(value, dict):
                    clean_dict = {k: v for k, v in value.items() if v is not None}
                    if clean_dict:
                        clean_filter[key] = clean_dict
                elif not isinstance(value, (list, dict)):
                    clean_filter[key] = value

        return {
            "filter": clean_filter
        }

    def _filter_by_items(self, receipts: List[Dict[str, Any]], filter_params: Dict) -> List[Dict[str, Any]]:
        """Filter receipts by item-level criteria"""

        categories = filter_params.get("categories", [])
        subcategories = filter_params.get("subcategories", [])
        keywords = filter_params.get("item_keywords", [])
        price_range = filter_params.get("price_range", {})

        if not categories and not subcategories and not keywords and not price_range:
            return receipts

        has_price_filter = False
        min_price = max_price = None
        if price_range:
            min_price = price_range.get("min")
            max_price = price_range.get("max")
            if min_price is not None and max_price is not None:
                min_price = float(min_price)
                max_price = float(max_price)
                has_price_filter = True

        filtered_receipts = []

        for receipt in receipts:
            receipt_matches = False
            items = receipt.get('items', [])

            for item in items:
                item_matches = True

                if categories:
                    if item.get('category', '') not in categories:
                        item_matches = False

                if subcategories and item_matches:
                    if item.get('subcategory', '') not in subcategories:
                        item_matches = False

                if keywords and item_matches:
                    item_name = item.get('name', '').lower()
                    if not any(keyword.lower() in item_name for keyword in keywords):
                        item_matches = False

                if has_price_filter and item_matches:
                    item_price = float(item.get('price', 0))
                    if not (min_price <= item_price <= max_price):
                        item_matches = False

                if item_matches:
                    receipt_matches = True
                    break

            if receipt_matches:
                filtered_receipts.append(receipt)

        logger.info(f"Filtered receipts: {len(filtered_receipts)} out of {len(receipts)}")
        return filtered_receipts
