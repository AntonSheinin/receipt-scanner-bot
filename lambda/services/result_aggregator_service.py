import logging
from typing import Any, Protocol
from enum import StrEnum
from dataclasses import dataclass
from collections import defaultdict

from config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

class AggregationType(StrEnum):
    """Aggregation types using StrEnum for better JSON serialization"""
    COUNT_RECEIPTS = "count_receipts"
    SUM_TOTAL = "sum_total"
    SUM_BY_CATEGORY = "sum_by_category"
    MIN_PRICE_BY_STORE = "min_price_by_store"
    MAX_PRICE_BY_STORE = "max_price_by_store"
    SUM_BY_PAYMENT = "sum_by_payment"
    LIST_STORES = "list_stores"

@dataclass(frozen=True)
class AggregationResult:
    """Immutable result container"""
    data: dict[str, Any]
    result_type: str
    metadata: dict[str, Any] | None = None

class Receipt(Protocol):
    """Type protocol for receipt structure"""
    total: float | str
    store_name: str
    payment_method: str
    items: list[dict[str, Any]]

class ResultAggregatorService:
    """Service for aggregating receipt data using modern Python patterns"""
    
    def __init__(self) -> None:
        # Method dispatch table - more pythonic than if/elif chain
        self._aggregators = {
            AggregationType.COUNT_RECEIPTS: self._count_receipts,
            AggregationType.SUM_TOTAL: self._sum_total,
            AggregationType.SUM_BY_CATEGORY: self._sum_by_category,
            AggregationType.MIN_PRICE_BY_STORE: lambda r, f: self._price_by_store(r, f, min),
            AggregationType.MAX_PRICE_BY_STORE: lambda r, f: self._price_by_store(r, f, max),
            AggregationType.SUM_BY_PAYMENT: self._sum_by_payment,
            AggregationType.LIST_STORES: self._list_stores,
        }
    
    def aggregate(self, receipts: list[dict[str, Any]], 
                  aggregation_type: AggregationType, 
                  filter_params: dict[str, Any]) -> AggregationResult:
        """Main aggregation dispatcher using method dispatch table"""
        try:
            aggregator = self._aggregators.get(aggregation_type, self._count_receipts)
            return aggregator(receipts, filter_params)
        except Exception as e:
            logger.error(f"Aggregation error: {e}")
            return AggregationResult(
                data={"error": str(e)}, 
                result_type="error"
            )
    
    def _count_receipts(self, receipts: list[dict[str, Any]], 
                       _: dict[str, Any]) -> AggregationResult:
        """Count receipts - simple and clean"""
        return AggregationResult(
            data={"count": len(receipts)}, 
            result_type="count"
        )
    
    def _sum_total(self, receipts: list[dict[str, Any]], 
                   _: dict[str, Any]) -> AggregationResult:
        """Sum total using generator expression for memory efficiency"""
        total = sum(
            self._safe_float(receipt.get('total', 0)) 
            for receipt in receipts 
            if receipt.get('total')
        )
        
        return AggregationResult(
            data={
                "total_spent": round(total, 2),
                "receipt_count": len(receipts)
            },
            result_type="sum_total"
        )
    
    def _sum_by_category(self, receipts: list[dict[str, Any]], 
                        filter_params: dict[str, Any]) -> AggregationResult:
        """Category breakdown using defaultdict and comprehensions"""
        categories = filter_params.get("categories", [])
        category_sums = defaultdict(float)
        
        for receipt in receipts:
            for item in receipt.get('items', []):
                item_category = item.get('category', 'other')
                
                if categories and not self._category_matches(item_category, categories):
                    continue
                
                price = (self._safe_float(item.get('price', 0)) * 
                        self._safe_int(item.get('quantity', 1)))
                category_sums[item_category] += price
        
        # Convert defaultdict to regular dict with rounding
        rounded_sums = {k: round(v, 2) for k, v in category_sums.items()}
        
        return AggregationResult(
            data={
                "category_totals": rounded_sums,
                "total_spent": round(sum(rounded_sums.values()), 2),
                "receipt_count": len(receipts)
            },
            result_type="category_breakdown"
        )
    
    def _price_by_store(self, receipts: list[dict[str, Any]], 
                       filter_params: dict[str, Any],
                       price_func: callable) -> AggregationResult:
        """Unified min/max price by store using callable parameter"""
        keywords = filter_params.get("item_keywords", [])
        categories = filter_params.get("categories", [])
        store_prices: dict[str, float] = {}
        
        for receipt in receipts:
            store = receipt.get('store_name', 'Unknown Store')
            
            # Use walrus operator for cleaner logic
            if matching_prices := [
                self._safe_float(item.get('price', 0))
                for item in receipt.get('items', [])
                if (self._item_matches_criteria(item, keywords, categories) and 
                    self._safe_float(item.get('price', 0)) > 0)
            ]:
                current_price = price_func(matching_prices)
                store_prices[store] = (
                    price_func(store_prices[store], current_price) 
                    if store in store_prices 
                    else current_price
                )
        
        return AggregationResult(
            data={
                "store_prices": {k: round(v, 2) for k, v in store_prices.items()},
                "keywords": keywords,
                "categories": categories,
                "comparison_type": price_func.__name__
            },
            result_type="price_comparison"
        )
    
    def _sum_by_payment(self, receipts: list[dict[str, Any]], 
                       filter_params: dict[str, Any]) -> AggregationResult:
        """Payment method breakdown using comprehension"""
        payment_methods = filter_params.get("payment_methods", [])
        
        payment_sums = defaultdict(float)
        for receipt in receipts:
            payment_method = receipt.get('payment_method', 'other')
            
            if not payment_methods or payment_method in payment_methods:
                payment_sums[payment_method] += self._safe_float(receipt.get('total', 0))
        
        rounded_sums = {k: round(v, 2) for k, v in payment_sums.items()}
        
        return AggregationResult(
            data={
                "payment_totals": rounded_sums,
                "total_spent": round(sum(rounded_sums.values()), 2),
                "receipt_count": len(receipts)
            },
            result_type="payment_breakdown"
        )
    
    def _list_stores(self, receipts: list[dict[str, Any]], 
                    _: dict[str, Any]) -> AggregationResult:
        """List unique stores using set comprehension"""
        stores = list({
            receipt.get('store_name', 'Unknown') 
            for receipt in receipts
        })
        
        return AggregationResult(
            data={
                "stores": stores,
                "store_count": len(stores),
                "receipt_count": len(receipts)
            },
            result_type="store_list"
        )
    
    # Helper methods - more robust and type-safe
    def _safe_float(self, value: Any) -> float:
        """Safely convert value to float"""
        try:
            return float(value) if value is not None else 0.0
        except (ValueError, TypeError):
            return 0.0
    
    def _safe_int(self, value: Any) -> int:
        """Safely convert value to int"""
        try:
            return int(value) if value is not None else 1
        except (ValueError, TypeError):
            return 1
    
    def _item_matches_criteria(self, item: dict[str, Any], 
                              keywords: list[str], 
                              categories: list[str]) -> bool:
        """Check if item matches criteria using all()"""
        item_name = item.get('name', '').lower()
        item_category = item.get('category', '').lower()
        
        keyword_match = (
            not keywords or 
            any(keyword.lower() in item_name for keyword in keywords)
        )
        
        category_match = (
            not categories or 
            self._category_matches(item_category, categories)
        )
        
        return keyword_match and category_match
    
    def _category_matches(self, item_category: str, categories: list[str]) -> bool:
        """Check category match using any() with generator"""
        item_lower = item_category.lower()
        return any(
            cat.lower() in item_lower or item_lower == cat.lower()
            for cat in categories
        )