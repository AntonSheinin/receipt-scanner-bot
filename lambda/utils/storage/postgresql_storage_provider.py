"""
    PostgreSQL Storage Provider module - Simplified
"""

import logging
import uuid
from typing import Optional, Dict, List, Any
import psycopg
from psycopg.rows import dict_row
from provider_interfaces import DocumentStorage
from config import setup_logging, get_database_connection_info
import json


setup_logging()
logger = logging.getLogger(__name__)

class PostgreSQLStorageProvider(DocumentStorage):
    """PostgreSQL implementation of DocumentStorage interface"""

    def __init__(self):
        self.connection_info = get_database_connection_info()
        self._connection_string = self._build_connection_string()

    def _build_connection_string(self) -> str:
        """Build psycopg3 connection string"""
        return (
            f"host={self.connection_info['host']} "
            f"port={self.connection_info['port']} "
            f"dbname={self.connection_info['database']} "
            f"user={self.connection_info['user']} "
            f"password={self.connection_info['password']}"
        )

    def _execute_query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Execute query and return results"""
        try:
            with psycopg.connect(self._connection_string, row_factory=dict_row) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    return cursor.fetchall()
        except Exception as e:
            logger.error(f"Query error: {e}")
            return []

    def _execute_single(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """Execute query and return single result"""
        results = self._execute_query(query, params)
        return results[0] if results else None

    def _execute_update(self, query: str, params: tuple = ()) -> bool:
        """Execute update and return success"""
        try:
            with psycopg.connect(self._connection_string) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    return True

        except Exception as e:
            logger.error(f"Update error: {e}")
            return False

    def save_receipt_with_items(self, user_id: str, receipt_data: Dict[str, Any]) -> bool:
        """Store receipt with items in one transaction"""

        receipt_id = receipt_data.get('receipt_id', str(uuid.uuid4()))

        try:
            with psycopg.connect(self._connection_string) as conn:
                with conn.cursor() as cursor:
                    # Insert receipt
                    cursor.execute("""
                        INSERT INTO receipts (id, user_id, store_name, date, total, payment_method,
                                            receipt_number, image_url)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            store_name = EXCLUDED.store_name,
                            purchasing_date = EXCLUDED.purchasing_date,
                            total = EXCLUDED.total,
                            payment_method = EXCLUDED.payment_method,
                            receipt_number = EXCLUDED.receipt_number,
                            image_url = EXCLUDED.image_url
                    """, (
                        receipt_id, user_id, receipt_data.get('store_name'),
                        receipt_data.get('date'), receipt_data.get('total'),
                        receipt_data.get('payment_method'), receipt_data.get('receipt_number'),
                        receipt_data.get('image_url')
                    ))

                    # Clear and insert items
                    cursor.execute("DELETE FROM receipt_items WHERE receipt_id = %s", (receipt_id,))

                    for item in receipt_data.get('items', []):
                        cursor.execute("""
                            INSERT INTO receipt_items (id, receipt_id, name, price, quantity,
                                                     category, subcategory, discount)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            str(uuid.uuid4()), receipt_id, item.get('name'),
                            item.get('price'), item.get('quantity'), item.get('category'),
                            item.get('subcategory'), item.get('discount')
                        ))

                    conn.commit()
                    return True

        except Exception as e:
            logger.error(f"Save receipt error: {e}")
            return False

    def get_filtered_receipts(self, user_id: str, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Get receipts with optional filtering"""

        where_conditions = ["r.user_id = %s"]
        params = [user_id]

        if filters:
            # Date range
            if filters.get('date_range'):
                dr = filters['date_range']
                if dr.get('start') and dr.get('end'):
                    where_conditions.append("r.purchasing_date BETWEEN %s AND %s")
                    params.extend([dr['start'], dr['end']])

            # Store names
            if filters.get('store_names'):
                where_conditions.append("r.store_name = ANY(%s)")
                params.append(filters['store_names'])

            # Payment methods
            if filters.get('payment_methods'):
                where_conditions.append("r.payment_method = ANY(%s)")
                params.append(filters['payment_methods'])

            # Price range
            if filters.get('price_range'):
                pr = filters['price_range']
                if pr.get('min') is not None and pr.get('max') is not None:
                    where_conditions.append("r.total BETWEEN %s AND %s")
                    params.extend([pr['min'], pr['max']])

            # Item filters - require JOIN
            item_filters = []

            if filters.get('categories'):
                item_filters.append("i.category = ANY(%s)")
                params.append(filters['categories'])

            if filters.get('subcategories'):
                item_filters.append("i.subcategory = ANY(%s)")
                params.append(filters['subcategories'])

            if filters.get('item_keywords'):
                keyword_parts = []
                for keyword in filters['item_keywords']:
                    keyword_parts.append("i.name ILIKE %s")
                    params.append(f"%{keyword}%")
                if keyword_parts:
                    item_filters.append(f"({' OR '.join(keyword_parts)})")

            where_conditions.extend(item_filters)

        # Build query
        where_clause = " AND ".join(where_conditions)
        limit_clause = f" LIMIT {int(filters['limit'])}" if filters and filters.get('limit') else ""

        query = f"""
            SELECT
                r.store_name,
                r.payment_method,
                r.receipt_number,
                r.purchasing_date::text AS purchasing_date,
                r.total::float8 AS total,
                r.created_at::text AS created_at,

                -- Aggregate items as JSON
                COALESCE(
                    JSON_AGG(
                        JSON_BUILD_OBJECT(
                            'name', i.name,
                            'price', i.price::float8,
                            'quantity', i.quantity::float8,
                            'category', i.category,
                            'subcategory', i.subcategory,
                            'discount', i.discount::float8
                        ) ORDER BY i.name
                    ) FILTER (WHERE i.id IS NOT NULL),
                    '[]'::json
                ) AS items

            FROM receipts r
            LEFT JOIN receipt_items i ON r.id = i.receipt_id
            WHERE {where_clause}
            GROUP BY r.id
            ORDER BY r.purchasing_date DESC, r.created_at DESC
            {limit_clause};
        """

        results = self._execute_query(query, tuple(params))

        # Parse JSON items
        for result in results:
            if isinstance(result.get('items'), str):
                result['items'] = json.loads(result['items'])

        return results

    def delete_receipt(self, user_id: str, receipt_id: str) -> bool:
        """Delete receipt (items cascade)"""
        return self._execute_update(
            "DELETE FROM receipts WHERE user_id = %s AND id = %s",
            (user_id, receipt_id)
        )

    def delete_last_uploaded_receipt(self, user_id: str) -> Optional[str]:
        """Delete most recent receipt and return image_url for cleanup"""
        result = self._execute_single("""
            DELETE FROM receipts
            WHERE user_id = %s AND id = (
                SELECT id FROM receipts
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 1
            )
            RETURNING image_url
        """, (user_id, user_id))

        return result['image_url'] if result and result['image_url'] else None

    def delete_all_receipts(self, user_id: str) -> List[str]:
        """Delete all receipts and return image_urls for cleanup"""
        results = self._execute_query(
            "DELETE FROM receipts WHERE user_id = %s RETURNING image_url",
            (user_id,)
        )

        # Return only non-null image URLs
        return [r['image_url'] for r in results if r.get('image_url')]

    def count_user_receipts(self, user_id: str) -> int:
        """Count user receipts"""
        result = self._execute_single(
            "SELECT COUNT(*) as count FROM receipts WHERE user_id = %s",
            (user_id,)
        )
        return result['count'] if result else 0
