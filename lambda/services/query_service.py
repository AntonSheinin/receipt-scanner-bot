"""
Query Processing Service
"""
import json
import logging
from typing import Dict, Optional, List, Any
from datetime import datetime, timedelta, timezone

from config import LLM_PROVIDER, setup_logging

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

    def process_query(self, question: str, user_id: str) -> Dict:
        """Handle natural language queries in 4 steps"""

        logger.info(f"Processing query: {question}")

        chat_id = int(user_id)
        secure_user_id = get_secure_user_id(user_id)

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
                self.telegram.send_message(chat_id, "❌ לא נמצאו נתונים תואמים. העלה קבלות קודם!")
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
            self.telegram.send_message(chat_id, "❌ הייתה בעיה בעיבוד השאלה שלך.")
            return create_response(200, {"status": "error"})

    def _generate_query_plan(self, question: str) -> Optional[Dict]:
        """Generate DynamoDB query plan using LLM"""

        prompt = self.prompts.get_generate_query_plan_prompt(question)

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

        # Get filtered receipts from storage
        receipts = self.storage.get_filtered_receipts(query_plan, user_id)
        if not receipts:
            logger.info("No receipts found for query")
            return None

        logger.info(f"Found {len(receipts)} receipts")

        try:
            # Apply item-level filtering
            filtered_receipts = self._filter_by_items(receipts, query_plan.get("filter", {}))
            logger.info(f"After filtering: {len(filtered_receipts)} receipts")

        except Exception as e:
            logger.error(f"Item filtering error: {e}")
            return None

        try:
            # Apply sorting
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
            # Apply aggregation
            aggregation_type = AggregationType(
                query_plan.get("aggregation", AggregationType.COUNT_RECEIPTS)
            )

            result = self.aggregator.aggregate(filtered_receipts, aggregation_type, filter_params)

            logger.info(f"Aggregation result: {result.data}")

            return {
                "query": query_plan,
                "results": result.data,
                "result_type": result.result_type,
                "raw_data": filtered_receipts[:3],  # Always show sample data for context
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

    def _sort_receipts(self, receipts: List[Dict], sort_by: str) -> List[Dict]:
        """Sort receipts based on criteria with robust error handling"""
        try:
            def safe_datetime_key(receipt: Dict[str, Any]) -> str:
                """Safely extract datetime for sorting"""
                created_at = receipt.get('created_at')
                if not created_at:
                    return '1900-01-01T00:00:00'

                # Handle various datetime formats
                if isinstance(created_at, str):
                    try:
                        # Try to parse and reformat to ensure consistent sorting
                        dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        return dt.isoformat()
                    except ValueError:
                        return '1900-01-01T00:00:00'
                return str(created_at)

            def safe_date_key(receipt: Dict[str, Any]) -> str:
                """Safely extract date for sorting"""
                date_val = receipt.get('date')
                if not date_val:
                    return '1900-01-01'

                if isinstance(date_val, str) and len(date_val) >= 10:
                    # Ensure YYYY-MM-DD format for proper string sorting
                    try:
                        # Validate date format
                        datetime.strptime(date_val[:10], '%Y-%m-%d')
                        return date_val[:10]
                    except ValueError:
                        pass
                return '1900-01-01'

            def safe_float_key(receipt: Dict[str, Any]) -> float:
                """Safely extract numeric total for sorting"""
                total = receipt.get('total', 0)
                try:
                    return float(total) if total is not None else 0.0
                except (ValueError, TypeError):
                    return 0.0

            # Mapping of sort criteria to sort functions
            sort_functions = {
                "upload_date_desc": lambda x: safe_datetime_key(x),
                "upload_date_asc": lambda x: safe_datetime_key(x),
                "receipt_date_desc": lambda x: safe_date_key(x),
                "receipt_date_asc": lambda x: safe_date_key(x),
                "total_desc": lambda x: safe_float_key(x),
                "total_asc": lambda x: safe_float_key(x),
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
                # Default to upload date desc
                return sorted(receipts, key=safe_datetime_key, reverse=True)

        except Exception as e:
            logger.error(f"Sorting error: {e}")
            return receipts

    def _filter_by_items(self, receipts: List[Dict], filter_params: Dict) -> List[Dict]:
        """Filter receipts by item-level criteria"""

        categories = filter_params.get("categories", [])
        keywords = filter_params.get("item_keywords", [])
        price_range = filter_params.get("price_range", {})

        # Remove empty lists and None values
        categories = [c for c in categories if c] if categories else []
        keywords = [k for k in keywords if k] if keywords else []

        # If no item-level filters, return all receipts
        if not categories and not keywords and not price_range:
            logger.info("No item-level filters specified, returning all receipts")
            return receipts

        # Check if price_range has valid values
        has_price_filter = False
        min_price = max_price = None
        if price_range and isinstance(price_range, dict):
            min_price = price_range.get("min")
            max_price = price_range.get("max")
            if min_price is not None and max_price is not None:
                try:
                    min_price = float(min_price)
                    max_price = float(max_price)
                    has_price_filter = True
                except (ValueError, TypeError):
                    pass

        filtered_receipts = []

        for receipt in receipts:
            items = receipt.get('items', [])
            receipt_matches = False

            for item in items:
                item_matches = True

                # Check category
                if categories:
                    item_category = item.get('category', '').lower()
                    if not any(cat.lower() in item_category or item_category == cat.lower() for cat in categories):
                        item_matches = False

                # Check keywords
                if keywords and item_matches:
                    item_name = item.get('name', '').lower()
                    if not any(keyword.lower() in item_name for keyword in keywords):
                        item_matches = False

                # Check price range
                if has_price_filter and item_matches:
                    try:
                        item_price = float(item.get('price', 0))
                        if not (min_price <= item_price <= max_price):
                            item_matches = False
                    except (ValueError, TypeError):
                        item_matches = False

                if item_matches:
                    receipt_matches = True
                    break

            if receipt_matches:
                filtered_receipts.append(receipt)

        return filtered_receipts
