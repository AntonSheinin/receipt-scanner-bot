"""
Query Processing Service
"""
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
            
            logger.info(f"Query plan: {query_plan}")
            
            # Step 2: Execute and aggregate
            results = self._execute_query(query_plan, user_id)
            if not results:
                self.telegram.send_message(chat_id, "❌ No matching data found. Upload some receipts first!")
                return create_response(200, {"status": "no_data"})
            
            logger.info(f"Results: {results['results']}")
            
            # Step 3: Generate response
            self.telegram.send_message(chat_id, "💭 Preparing your answer...")
            response = self.llm.generate_response(question, results)
            
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

Generate a JSON query plan with this structure:
{{
    "filter": {{
        "date_range": {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}},
        "store_names": ["store1", "store2"],
        "item_keywords": ["keyword1", "keyword2"],
        "categories": ["food", "beverages", "household"],
        "price_range": {{"min": 0, "max": 100}}
    }},
    "aggregation": "sum_total|sum_by_category|min_price_by_store|max_price_by_store|count_receipts|list_stores|list_items"
}}

Rules:
- Only include filter fields that are relevant to the question
- For date queries like "August", "last month", "this month", use appropriate date ranges
- For "last month" use: {last_month}-01 to {last_month}-31
- For "this month" use: {current_month}-01 to {current_date.strftime('%Y-%m-%d')}
- For price comparison questions, use min_price_by_store or max_price_by_store
- For spending questions, use sum_total or sum_by_category
- For counting questions, use count_receipts
- Item keywords should include both English and Hebrew terms when possible
- Categories: food, beverages, household, electronics, clothing, pharmacy, health, other

Examples:
"How much did I spend on food in August?" → date_range: August 2025, categories: ["food"], aggregation: "sum_by_category"
"Which store has cheapest milk?" → item_keywords: ["milk", "חלב"], aggregation: "min_price_by_store"
"How many receipts from Rami Levy?" → store_names: ["Rami Levy"], aggregation: "count_receipts"
"How much did I spend last month?" → date_range: last month, aggregation: "sum_total"

Return ONLY the JSON object, no explanations, no markdown"""

            return self.llm.generate_query_plan(prompt)
            
        except Exception as e:
            logger.error(f"Query plan error: {e}")
            return None
    
    def _execute_query(self, query_plan: Dict, user_id: str) -> Optional[Dict]:
        """Execute query and aggregate results"""
        try:
            # Get filtered receipts from storage
            receipts = self.storage.get_filtered_receipts(query_plan, user_id)
            if not receipts:
                return None
            
            logger.info(f"Found {len(receipts)} receipts")
            
            # Apply item-level filtering
            filtered_receipts = self._filter_by_items(receipts, query_plan.get("filter", {}))
            logger.info(f"After filtering: {len(filtered_receipts)} receipts")
            
            # Apply aggregation
            aggregation_type = query_plan.get("aggregation", "count_receipts")
            results = self._aggregate_results(filtered_receipts, query_plan.get("filter", {}), aggregation_type)
            
            return {
                "query": query_plan,
                "results": results,
                "raw_data": filtered_receipts[:3],
                "total_receipts": len(filtered_receipts)
            }
            
        except Exception as e:
            logger.error(f"Query execution error: {e}")
            return None
    
    def _filter_by_items(self, receipts: List[Dict], filter_params: Dict) -> List[Dict]:
        """Filter receipts by item-level criteria"""
        try:
            categories = filter_params.get("categories", [])
            keywords = filter_params.get("item_keywords", [])
            price_range = filter_params.get("price_range", {})
            
            # If no item-level filters, return all receipts
            if not categories and not keywords and not price_range:
                return receipts
            
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
                    if price_range and item_matches:
                        item_price = float(item.get('price', 0))
                        min_price = price_range.get('min', 0)
                        max_price = price_range.get('max', float('inf'))
                        if not (min_price <= item_price <= max_price):
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
            
            else:
                return {"receipt_count": len(receipts), "type": "default"}
        
        except Exception as e:
            logger.error(f"Aggregation error: {e}")
            return {"error": str(e), "type": "error"}