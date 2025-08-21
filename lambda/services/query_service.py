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

    def _validate_filter_plan(self, query_plan: Dict[str, Any]) -> Dict[str, Any]:
        """Clean and validate filter plan - remove empty/null values"""

        def clean_value(value: Any) -> Any | None:
            if value is None:
                return None

            if isinstance(value, list):
                return value if value else None

            if isinstance(value, dict):
                cleaned = {k: v for k, v in value.items() if v is not None}
                return cleaned if cleaned else None

            return value

        filter_params = query_plan.get("filter", {}) or {}

        clean_filter = {
            key: cleaned
            for key, value in filter_params.items()
            if (cleaned := clean_value(value)) is not None
        }

        return {"filter": clean_filter}

    def _filter_by_items(self, receipts: List[Dict[str, Any]], filter_params: Dict) -> List[Dict[str, Any]]:
        """Filter receipts by item-level criteria"""

        categories: List[str] = filter_params.get("categories", [])
        subcategories: List[str] = filter_params.get("subcategories", [])
        keywords: List[str] = filter_params.get("item_keywords", [])
        price_range: Dict[str, Any] = filter_params.get("price_range", {})

        if not (categories or subcategories or keywords or price_range):
            return receipts

        min_price = price_range.get("min")
        max_price = price_range.get("max")
        has_price_filter = min_price is not None and max_price is not None

        if has_price_filter:
            min_price, max_price = float(min_price), float(max_price)

        def item_matches(item: Dict[str, Any]) -> bool:
            """Check if a single item matches all filters."""
            if categories and item.get("category") not in categories:
                return False

            if subcategories and item.get("subcategory") not in subcategories:
                return False

            if keywords:
                name = (item.get("name") or "").lower()
                if not any(kw.lower() in name for kw in keywords):
                    return False

            if has_price_filter:
                try:
                    price = float(item.get("price", 0))
                except (TypeError, ValueError):
                    return False
                if not (min_price <= price <= max_price):
                    return False

            return True

        # Keep receipts that have at least one matching item
        filtered = [receipt for receipt in receipts if any(item_matches(item) for item in receipt.get("items", []))]

        logger.info("Filtered receipts: %d out of %d", len(filtered), len(receipts))
        return filtered
