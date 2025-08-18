"""
    Result Aggregator Service module
"""

import logging
from typing import Any, List, Dict
from enum import StrEnum
from dataclasses import dataclass
from collections import defaultdict
from decimal import Decimal
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


class ResultAggregatorService:
    """Service for aggregating receipt data using modern Python patterns"""

    def __init__(self) -> None:

        self._aggregators = {
            AggregationType.COUNT_RECEIPTS: self._count_receipts,
            AggregationType.SUM_TOTAL: self._sum_total,
            AggregationType.SUM_BY_CATEGORY: self._sum_by_category,
            AggregationType.MIN_PRICE_BY_STORE: lambda r, f: self._price_by_store(r, f, min),
            AggregationType.MAX_PRICE_BY_STORE: lambda r, f: self._price_by_store(r, f, max),
            AggregationType.SUM_BY_PAYMENT: self._sum_by_payment,
            AggregationType.LIST_STORES: self._list_stores,
        }

    def aggregate(self, receipts: List[Dict[str, Any]], aggregation_type: AggregationType, filter_params: Dict[str, Any]) -> AggregationResult:
        """Main aggregation dispatcher using method dispatch table - works with raw dicts"""

        logger.info(f"Aggregating {len(receipts)} receipts with type: {aggregation_type}")

        try:
            aggregator = self._aggregators.get(aggregation_type, self._count_receipts)
            return aggregator(receipts, filter_params)

        except Exception as e:
            logger.error(f"Aggregation error: {e}")
            return AggregationResult(
                data={"error": str(e)},
                result_type="error"
            )

    def _count_receipts(self, receipts: List[Dict[str, Any]], _: Dict[str, Any]) -> AggregationResult:
        """Count receipts - works with raw dicts"""
        logger.info(f"Counting receipts: {len(receipts)} found")

        return AggregationResult(
            data={"count": len(receipts)},
            result_type="count"
        )

    def _sum_total(self, receipts: List[Dict[str, Any]], _: Dict[str, Any]) -> AggregationResult:
        """Sum total using generator expression - works with raw dicts"""
        logger.info("Calculating total spent across all receipts")

        total = sum(Decimal(str(receipt.get('total', 0))) for receipt in receipts)

        return AggregationResult(
            data={
                "total_spent": float(total),
                "receipt_count": len(receipts)
            },
            result_type="sum_total"
        )

    def _sum_by_category(self, receipts: List[Dict[str, Any]], filter_params: Dict[str, Any]) -> AggregationResult:
        """Category breakdown using defaultdict - works with raw dicts"""
        logger.info("Calculating total spent by category/subcategory")

        categories = filter_params.get("categories", [])
        subcategories = filter_params.get("subcategories", [])
        category_sums = defaultdict(Decimal)
        subcategory_sums = defaultdict(Decimal)

        for receipt in receipts:
            items = receipt.get('items', [])
            for item in items:
                # Check if item matches filters
                item_category = item.get('category', '')
                item_subcategory = item.get('subcategory', '')

                category_match = not categories or item_category in categories
                subcategory_match = not subcategories or item_subcategory in subcategories

                if category_match and subcategory_match:
                    price = Decimal(str(item.get('price', 0)))
                    quantity = Decimal(str(item.get('quantity', 1)))
                    discount = Decimal(str(item.get('discount', 0)))

                    item_total = (price * quantity) + discount
                    category_sums[item_category] += item_total
                    subcategory_sums[item_subcategory] += item_total

        # Convert to float for JSON serialization
        category_totals = {k: float(v) for k, v in category_sums.items()}
        subcategory_totals = {k: float(v) for k, v in subcategory_sums.items()}

        return AggregationResult(
            data={
                "category_totals": category_totals,
                "subcategory_totals": subcategory_totals,
                "total_spent": sum(category_totals.values()),
                "receipt_count": len(receipts)
            },
            result_type="category_breakdown"
        )

    def _price_by_store(self, receipts: List[Dict[str, Any]], filter_params: Dict[str, Any], price_func) -> AggregationResult:
        """Unified min/max price by store - works with raw dicts"""
        logger.info(f"Calculating {price_func.__name__} price by store")

        keywords = filter_params.get("item_keywords", [])
        categories = filter_params.get("categories", [])
        subcategories = filter_params.get("subcategories", [])
        store_prices: Dict[str, Decimal] = {}

        for receipt in receipts:
            store = receipt.get('store_name', 'Unknown Store')
            items = receipt.get('items', [])

            matching_prices = [
                Decimal(str(item.get('price', 0))) for item in items
                if (self._item_matches_criteria_dict(item, keywords, categories, subcategories)
                    and float(item.get('price', 0)) > 0)
            ]

            if matching_prices:
                current_price = price_func(matching_prices)
                store_prices[store] = price_func(store_prices[store], current_price) if store in store_prices else current_price

        return AggregationResult(
            data={
                "store_prices": {k: float(v) for k, v in store_prices.items()},
                "keywords": keywords,
                "categories": categories,
                "subcategories": subcategories,
                "comparison_type": price_func.__name__
            },
            result_type="price_comparison"
        )

    def _sum_by_payment(self, receipts: List[Dict[str, Any]], filter_params: Dict[str, Any]) -> AggregationResult:
        """Payment method breakdown - works with raw dicts"""
        logger.info("Calculating total spent by payment method")

        payment_methods = filter_params.get("payment_methods", [])
        payment_sums = defaultdict(Decimal)

        for receipt in receipts:
            payment_method = receipt.get('payment_method', 'other')
            if not payment_methods or payment_method in payment_methods:
                total = Decimal(str(receipt.get('total', 0)))
                payment_sums[payment_method] += total

        rounded_sums = {k: float(v) for k, v in payment_sums.items()}

        return AggregationResult(
            data={
                "payment_totals": rounded_sums,
                "total_spent": sum(rounded_sums.values()),
                "receipt_count": len(receipts)
            },
            result_type="payment_breakdown"
        )

    def _list_stores(self, receipts: List[Dict[str, Any]], _: Dict[str, Any]) -> AggregationResult:
        """List unique stores - works with raw dicts"""
        logger.info("Listing unique stores from receipts")

        stores = list({receipt.get('store_name', 'Unknown Store') for receipt in receipts})

        return AggregationResult(
            data={
                "stores": stores,
                "store_count": len(stores),
                "receipt_count": len(receipts)
            },
            result_type="store_list"
        )

    def _item_matches_criteria_dict(self, item: Dict[str, Any], keywords: List[str], categories: List[str], subcategories: List[str] = None) -> bool:
        """Check if item dict matches criteria"""
        item_name = item.get('name', '').lower()
        item_category = item.get('category', '')
        item_subcategory = item.get('subcategory', '')

        keyword_match = not keywords or any(keyword.lower() in item_name for keyword in keywords)
        category_match = not categories or item_category in categories
        subcategory_match = not subcategories or item_subcategory in subcategories

        return keyword_match and category_match and subcategory_match
