"""
Query Processing Service
"""
import json
import logging
from typing import Dict, Optional, List
from datetime import datetime, timedelta, timezone

from config import setup_logging

from .telegram_service import TelegramService
from .storage_service import StorageService
from utils.llm_client import LLMClient
from utils.helpers import create_response


setup_logging()
logger = logging.getLogger(__name__)

class QueryService:
    """Service for natural language query processing"""
    
    def __init__(self):
        self.telegram = TelegramService()
        self.storage = StorageService()
        self.llm = LLMClient()
    
    def process_query(self, question: str, user_id: str) -> Dict:
        """Handle natural language queries in 4 steps"""
        chat_id = int(user_id)
        
        try:
            self.telegram.send_typing(chat_id)
            self.telegram.send_message(chat_id, "🔍 Analyzing your question...")
            
            # Step 1: Generate query plan
            query_plan = self._generate_query_plan(question)
            if not query_plan:
                self.telegram.send_message(chat_id, "❌ Couldn't understand your question. Try rephrasing it.")
                return create_response(200, {"status": "failed"})
            
            logger.info(f"Query plan for '{question}': {json.dumps(query_plan, indent=2)}")
            
            # Step 2: Execute and aggregate
            results = self._execute_query(query_plan, user_id)
            if not results:
                self.telegram.send_message(chat_id, "❌ No matching data found. Upload some receipts first!")
                return create_response(200, {"status": "no_data"})
            
            logger.info(f"Aggregation results: {json.dumps(results['results'], indent=2)}")
            
            # Step 3: Generate response
            self.telegram.send_message(chat_id, "💭 Preparing your answer...")
            response = self.llm.generate_response(question, results)

            logger.info(f"LLM response: {response}")
            
            # Step 4: Send to user
            if response:
                self.telegram.send_message(chat_id, response)
            else:
                self.telegram.send_message(chat_id, "❌ Had trouble generating response. Try rephrasing.")
            
            return create_response(200, {"status": "completed"})
            
        except Exception as e:
            logger.error(f"Query error: {e}", exc_info=True)
            self.telegram.send_message(chat_id, "❌ Error processing your question.")
            return create_response(200, {"status": "error"})
    
    def _generate_query_plan(self, question: str) -> Optional[Dict]:
        """Generate DynamoDB query plan using LLM"""
        try:
            current_date = datetime.now(timezone.utc)
            current_month = current_date.strftime('%Y-%m')
            last_month = (current_date.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
            
            prompt = f"""Analyze this user question about their stored receipts and generate a query plan.

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

            # Get filtered receipts from storage
            receipts = self.storage.get_filtered_receipts(query_plan, user_id)
            if not receipts:
                return None
            
            logger.info(f"Found {len(receipts)} receipts")
            
            # Apply item-level filtering
            filtered_receipts = self._filter_by_items(receipts, query_plan.get("filter", {}))
            logger.info(f"After filtering: {len(filtered_receipts)} receipts")
            
            # Apply sorting
            sort_by = query_plan.get("sort_by", "date_desc")
            filtered_receipts = self._sort_receipts(filtered_receipts, sort_by)
            
            # Apply limit
            filter_params = query_plan.get("filter", {})
            limit = filter_params.get("limit")
            if limit and isinstance(limit, int) and limit > 0:
                filtered_receipts = filtered_receipts[:limit]
                logger.info(f"After limit {limit}: {len(filtered_receipts)} receipts")
            
            # Apply aggregation
            aggregation_type = query_plan.get("aggregation", "count_receipts")
            results = self._aggregate_results(filtered_receipts, filter_params, aggregation_type)
            
            return {
                "query": query_plan,
                "results": results,
                "raw_data": filtered_receipts[:3],  # Always show sample data for context
                "total_receipts": len(filtered_receipts)
            }
            
        except Exception as e:
            logger.error(f"Query execution error: {e}")
            return None
        
    def _validate_query_plan(self, query_plan: Dict) -> Dict:
        """Clean and validate query plan"""
        try:
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
            
            # Ensure we have valid sort_by
            sort_by = query_plan.get("sort_by", "upload_date_desc")
            
            return {
                "filter": clean_filter,
                "aggregation": aggregation,
                "sort_by": sort_by
            }
        
        except Exception as e:
            logger.error(f"Query plan validation error: {e}")
            return {"filter": {}, "aggregation": "count_receipts", "sort_by": "upload_date_desc"}
    
    def _sort_receipts(self, receipts: List[Dict], sort_by: str) -> List[Dict]:
        """Sort receipts based on criteria"""
        try:
            if sort_by == "upload_date_desc":
                return sorted(receipts, key=lambda x: x.get('created_at', '1900-01-01T00:00:00'), reverse=True)
            elif sort_by == "upload_date_asc":
                return sorted(receipts, key=lambda x: x.get('created_at', '1900-01-01T00:00:00'))
            elif sort_by == "receipt_date_desc":
                return sorted(receipts, key=lambda x: x.get('date', '1900-01-01'), reverse=True)
            elif sort_by == "receipt_date_asc":
                return sorted(receipts, key=lambda x: x.get('date', '1900-01-01'))
            elif sort_by == "total_desc":
                return sorted(receipts, key=lambda x: float(x.get('total', 0)), reverse=True)
            elif sort_by == "total_asc":
                return sorted(receipts, key=lambda x: float(x.get('total', 0)))
            else:
                # Default to upload date desc for "last uploaded"
                return sorted(receipts, key=lambda x: x.get('created_at', '1900-01-01T00:00:00'), reverse=True)
        except Exception as e:
            logger.error(f"Sorting error: {e}")
            return receipts
    
    def _filter_by_items(self, receipts: List[Dict], filter_params: Dict) -> List[Dict]:
        """Filter receipts by item-level criteria"""
        try:
            categories = filter_params.get("categories", [])
            keywords = filter_params.get("item_keywords", [])
            price_range = filter_params.get("price_range", {})
            
            # Remove empty lists and None values
            categories = [c for c in categories if c] if categories else []
            keywords = [k for k in keywords if k] if keywords else []
            
            # If no item-level filters, return all receipts
            if not categories and not keywords and not price_range:
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
            
        except Exception as e:
            logger.error(f"Item filtering error: {e}")
            return receipts
    
    def _aggregate_results(self, receipts: List[Dict], filter_params: Dict, aggregation_type: str) -> Dict:
        """Apply aggregation to filtered receipts"""
        try:
            if aggregation_type == "count_receipts":
                return {"count": len(receipts), "type": "count"}
            
            elif aggregation_type == "sum_total":
                total = sum(float(receipt.get('total', 0)) for receipt in receipts if receipt.get('total'))
                return {"total_spent": round(total, 2), "receipt_count": len(receipts), "type": "sum_total"}
            
            elif aggregation_type == "sum_by_category":
                category_sums = {}
                categories = filter_params.get("categories", [])
                
                for receipt in receipts:
                    for item in receipt.get('items', []):
                        item_category = item.get('category', 'other')
                        
                        # If categories filter specified, only include matching items
                        if categories and not any(cat.lower() in item_category.lower() or item_category.lower() == cat.lower() for cat in categories):
                            continue
                        
                        price = float(item.get('price', 0)) * int(item.get('quantity', 1))
                        category_sums[item_category] = category_sums.get(item_category, 0) + price
                
                category_sums = {k: round(v, 2) for k, v in category_sums.items()}
                
                return {
                    "category_totals": category_sums,
                    "total_spent": round(sum(category_sums.values()), 2),
                    "receipt_count": len(receipts),
                    "type": "category_breakdown"
                }
            
            elif aggregation_type in ["min_price_by_store", "max_price_by_store"]:
                keywords = filter_params.get("item_keywords", [])
                categories = filter_params.get("categories", [])
                store_prices = {}
                
                for receipt in receipts:
                    store = receipt.get('store_name', 'Unknown Store')
                    for item in receipt.get('items', []):
                        item_name = item.get('name', '').lower()
                        item_category = item.get('category', '').lower()
                        
                        item_matches = True
                        
                        # Check keywords
                        if keywords and not any(keyword.lower() in item_name for keyword in keywords):
                            item_matches = False
                        
                        # Check categories
                        if categories and item_matches and not any(cat.lower() in item_category or item_category == cat.lower() for cat in categories):
                            item_matches = False
                        
                        if item_matches:
                            price = float(item.get('price', 0))
                            if price > 0:
                                if store not in store_prices:
                                    store_prices[store] = price
                                elif aggregation_type == "min_price_by_store":
                                    store_prices[store] = min(store_prices[store], price)
                                else:
                                    store_prices[store] = max(store_prices[store], price)
                
                store_prices = {k: round(v, 2) for k, v in store_prices.items()}
                
                return {
                    "store_prices": store_prices,
                    "keywords": keywords,
                    "categories": categories,
                    "type": "price_comparison",
                    "comparison_type": "min" if aggregation_type == "min_price_by_store" else "max"
                }
            
            elif aggregation_type == "list_stores":
                stores = list(set(receipt.get('store_name', 'Unknown') for receipt in receipts))
                return {"stores": stores, "store_count": len(stores), "receipt_count": len(receipts), "type": "store_list"}
            
            elif aggregation_type == "sum_by_payment":
                payment_sums = {}
                payment_methods = filter_params.get("payment_methods", [])
                
                for receipt in receipts:
                    payment_method = receipt.get('payment_method', 'other')
                    
                    # If payment methods filter specified, only include matching receipts
                    if payment_methods and payment_method not in payment_methods:
                        continue
                    
                    total = float(receipt.get('total', 0))
                    payment_sums[payment_method] = payment_sums.get(payment_method, 0) + total
                
                payment_sums = {k: round(v, 2) for k, v in payment_sums.items()}
                
                return {
                    "payment_totals": payment_sums,
                    "total_spent": round(sum(payment_sums.values()), 2),
                    "receipt_count": len(receipts),
                    "type": "payment_breakdown"
                }
            
            else:
                return {"receipt_count": len(receipts), "type": "default"}
        
        except Exception as e:
            logger.error(f"Aggregation error: {e}")
            return {"error": str(e), "type": "error"}