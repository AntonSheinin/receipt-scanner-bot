"""
    Query Processing Service module
"""

import json
import logging
from typing import Dict, Optional, List
from config import LLM_PROVIDER, setup_logging
from receipt_schemas import ReceiptData
from services.telegram_service import TelegramService
from services.storage_service import StorageService
from services.llm_service import LLMService
from services.result_aggregator_service import ResultAggregatorService, AggregationType
from utils.helpers import create_response, get_secure_user_id
from utils.llm.prompts import PromptManager


setup_logging()
logger = logging.getLogger(__name__)

class QueryService:
    """Service for natural language query processing"""

    def __init__(self):
        self.telegram = TelegramService()
        self.storage = StorageService()
        self.llm = LLMService(LLM_PROVIDER)
        self.aggregator = ResultAggregatorService()
        self.prompts = PromptManager()

    def process_query(self, question: str, chat_id: int) -> Dict:
        """Handle natural language queries in 4 steps"""

        logger.info(f"Processing query: {question}")

        secure_user_id = get_secure_user_id(chat_id)

        try:
            self.telegram.send_typing(chat_id)
            self.telegram.send_message(chat_id, "🔍 מנתחים את שאלתך...")

            # Step 1: Generate query plan
            query_plan = self._generate_query_plan(question)
            if not query_plan:
                self.telegram.send_message(chat_id, "❌ לא הצלחנו להבין את השאלתך. נסה לנסח מחדש.")
                logger.error(f"Failed to generate query plan for question: {question}")
                return create_response(200, {"status": "failed"})

            logger.info(f"Query plan for '{question}': {json.dumps(query_plan, indent=2)}")

            # Step 2: Execute and aggregate
            results = self._execute_query(query_plan, secure_user_id)
            if not results:
                self.telegram.send_message(chat_id, "❌ לא נמצאו נתונים תואמים!")
                logger.info("No matching data found for query")
                return create_response(200, {"status": "no_data"})

            logger.info(f"Aggregation results: {json.dumps(results['results'], indent=2)}")

            # Step 3: Generate response
            self.telegram.send_message(chat_id, "💭 מכינים את התשובה ...")
            response = self.llm.generate_response(question, results)

            logger.info(f"LLM response: {response}")

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
            self.telegram.send_message(chat_id, "❌ הייתה בעיה בעיבוד השאלתך.")
            return create_response(200, {"status": "error"})

    def _generate_query_plan(self, question: str) -> Optional[Dict]:
        """Generate DynamoDB query plan using LLM"""

        prompt = self.prompts.get_query_plan_prompt(question)

        try:
            return self.llm.generate_query_plan(prompt)

        except Exception as e:
            logger.error(f"Query plan error: {e}")
            return None

    def _execute_query(self, query_plan: Dict, user_id: str) -> Optional[Dict]:
        """Execute query and aggregate results"""
        try:
            # Validate and clean query plan
            query_plan = self._validate_query_plan(query_plan)
            logger.info(f"Cleaned query plan: {json.dumps(query_plan, indent=2)}")
        except Exception as e:
            logger.error(f"Query plan validation error: {e}")
            return None

        logger.info("Executing query with cleaned plan")

        # Get filtered receipts from storage - returns List[ReceiptData]
        receipts = self.storage.get_filtered_receipts(query_plan, user_id)
        if not receipts:
            logger.info("No receipts found for query")
            return None

        logger.info(f"Found {len(receipts)} receipts")

        try:
            # Apply item-level filtering - now works with ReceiptData objects
            filtered_receipts = self._filter_by_items(receipts, query_plan.get("filter", {}))
            logger.info(f"After filtering: {len(filtered_receipts)} receipts")
        except Exception as e:
            logger.error(f"Item filtering error: {e}")
            return None

        try:
            # Apply sorting - works with ReceiptData objects
            sort_by = query_plan.get("sort_by", "date_desc")
            filtered_receipts = self._sort_receipts(filtered_receipts, sort_by)
            logger.info(f"After sorting by '{sort_by}': {len(filtered_receipts)} receipts")
        except Exception as e:
            logger.error(f"Sorting error: {e}")
            return None

        # Apply limit
        filter_params = query_plan.get("filter", {})
        limit = filter_params.get("limit")

        if limit and isinstance(limit, int) and limit > 0:
            filtered_receipts = filtered_receipts[:limit]
            logger.info(f"After limit {limit}: {len(filtered_receipts)} receipts")

        try:
            # Apply aggregation - works with ReceiptData objects
            aggregation_type = AggregationType(
                query_plan.get("aggregation", AggregationType.COUNT_RECEIPTS)
            )

            result = self.aggregator.aggregate(filtered_receipts, aggregation_type, filter_params)

            logger.info(f"Aggregation result: {result.data}")

            # Convert ReceiptData objects to dict for raw_data (for LLM context)
            raw_data_dicts = [receipt.model_dump() for receipt in filtered_receipts[:10]]

            return {
                "query": query_plan,
                "results": result.data,
                "result_type": result.result_type,
                "raw_data": raw_data_dicts,  # Convert to dict for LLM
                "total_receipts": len(filtered_receipts)
            }

        except Exception as e:
            logger.error(f"Aggregation error: {e}")
            return None

    def _validate_query_plan(self, query_plan: Dict) -> Dict:
        """Clean and validate query plan"""

        # Clean up filter
        clean_filter = {}
        filter_params = query_plan.get("filter", {})

        # Only include non-null, non-empty values
        for key, value in filter_params.items():
            if value is not None:
                if isinstance(value, list) and len(value) > 0:
                    clean_filter[key] = value
                elif isinstance(value, dict):
                    # For price_range and date_range, check if they have valid values
                    clean_dict = {k: v for k, v in value.items() if v is not None}
                    if clean_dict:
                        clean_filter[key] = clean_dict
                elif not isinstance(value, (list, dict)):
                    clean_filter[key] = value

        # Ensure we have valid aggregation
        aggregation = query_plan.get("aggregation")
        if not aggregation:
            aggregation = "count_receipts"
            logger.warning("No aggregation specified, defaulting to 'count_receipts'")

        # Ensure we have valid sort_by
        sort_by = query_plan.get("sort_by", "upload_date_desc")

        return {
            "filter": clean_filter,
            "aggregation": aggregation,
            "sort_by": sort_by
        }

    def _sort_receipts(self, receipts: List[ReceiptData], sort_by: str) -> List[ReceiptData]:
        """Sort receipts based on criteria with robust error handling"""
        # Mapping of sort criteria to sort functions
        sort_functions = {
            "upload_date_desc": lambda r: r.created_at if hasattr(r, 'created_at') else '1900-01-01T00:00:00',
            "upload_date_asc": lambda r: r.created_at if hasattr(r, 'created_at') else '1900-01-01T00:00:00',
            "receipt_date_desc": lambda r: r.date,
            "receipt_date_asc": lambda r: r.date,
            "total_desc": lambda r: r.total,
            "total_asc": lambda r: r.total,
        }

        # Determine reverse flag
        reverse_sorts = {"upload_date_desc", "receipt_date_desc", "total_desc"}

        if sort_by in sort_functions:
            return sorted(
                receipts,
                key=sort_functions[sort_by],
                reverse=sort_by in reverse_sorts
            )
        else:
            # Default to receipt date desc
            return sorted(receipts, key=lambda r: r.date, reverse=True)

    def _filter_by_items(self, receipts: List[ReceiptData], filter_params: Dict) -> List[ReceiptData]:
        """Filter receipts by item-level criteria including subcategories"""

        categories = filter_params.get("categories", [])
        subcategories = filter_params.get("subcategories", [])
        keywords = filter_params.get("item_keywords", [])
        price_range = filter_params.get("price_range", {})

        if not categories and not subcategories and not keywords and not price_range:
            logger.info("No item-level filters specified")
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

            for item in receipt.items:
                item_matches = True

                if categories:
                    if item.category not in categories:
                        item_matches = False

                if subcategories and item_matches:
                    if item.subcategory not in subcategories:
                        item_matches = False

                if keywords and item_matches:
                    item_name = item.name.lower()
                    if not any(keyword.lower() in item_name for keyword in keywords):
                        item_matches = False

                if has_price_filter and item_matches:
                    if not (min_price <= float(item.price) <= max_price):
                        item_matches = False

                if item_matches:
                    receipt_matches = True
                    break

            if receipt_matches:
                filtered_receipts.append(receipt)

        logger.info(f"Filtered receipts: {len(filtered_receipts)} out of {len(receipts)}")
        return filtered_receipts
