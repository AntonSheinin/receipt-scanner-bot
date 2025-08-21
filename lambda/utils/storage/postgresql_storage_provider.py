"""
    PostgreSQL Storage Provider module - Simplified
"""

import logging
import uuid
from typing import Any, Literal
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
        self._connection_string = (
            f"host={self.connection_info['host']} "
            f"port={self.connection_info['port']} "
            f"dbname={self.connection_info['database']} "
            f"user={self.connection_info['user']} "
            f"password={self.connection_info['password']}"
        )

    def _execute(self, query: str, params: tuple = (), fetch: Literal["all", "one", "none"] = "none") -> Any:
        """Generic query executor with flexible fetch mode"""
        try:
            with psycopg.connect(self._connection_string, row_factory=dict_row) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    if fetch == "all":
                        return cursor.fetchall()
                    elif fetch == "one":
                        return cursor.fetchone()
                    return True

        except Exception as e:
            logger.error(f"Database error: {e}, Query: {query}, Params: {params}")
            return [] if fetch == "all" else None if fetch == "one" else False

    # ----------------- Receipt Operations -----------------

    def save_receipt_with_items(self, user_id: str, receipt_data: dict[str, Any]) -> bool:
        """Store receipt with items in one transaction"""

        receipt_id = receipt_data.get('receipt_id', str(uuid.uuid4()))
        items = receipt_data.get('items', [])

        try:
            with psycopg.connect(self._connection_string) as conn:
                with conn.cursor() as cursor:
                    # Insert receipt
                    cursor.execute("""
                        INSERT INTO receipts (id, user_id, store_name, purchasing_date, total, payment_method, receipt_number, image_url)
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
                        receipt_data.get('purchasing_date'), receipt_data.get('total'),
                        receipt_data.get('payment_method'), receipt_data.get('receipt_number'),
                        receipt_data.get('image_url')
                    ))

                    # Clear and insert items
                    cursor.execute("DELETE FROM receipt_items WHERE receipt_id = %s", (receipt_id,))

                    cursor.executemany("""
                        INSERT INTO receipt_items (id, receipt_id, name, price, quantity, category, subcategory, discount)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                        [
                            (
                                str(uuid.uuid4()), receipt_id, item.get("name"), item.get("price"),
                                item.get("quantity"), item.get("category"),
                                item.get("subcategory"), item.get("discount"),
                            )
                            for item in items
                        ],
                    )

                    return True

        except Exception as e:
            logger.error(f"Save receipt error: {e}")
            return False

    def get_filtered_receipts(self, user_id: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Get receipts with optional filtering"""
        where = ["r.user_id = %s"]
        params = [user_id]

        if filters:
            if dr := filters.get("date_range"):
                if dr.get("start") and dr.get("end"):
                    where.append("r.purchasing_date BETWEEN %s AND %s")
                    params.extend([dr["start"], dr["end"]])

            if stores := filters.get("store_names"):
                where.append("r.store_name = ANY(%s)")
                params.append(stores)

            if methods := filters.get("payment_methods"):
                where.append("r.payment_method = ANY(%s)")
                params.append(methods)

            if pr := filters.get("price_range"):
                if pr.get("min") is not None and pr.get("max") is not None:
                    where.append("r.total BETWEEN %s AND %s")
                    params.extend([pr["min"], pr["max"]])

            if cats := filters.get("categories"):
                where.append("i.category = ANY(%s)")
                params.append(cats)

            if subs := filters.get("subcategories"):
                where.append("i.subcategory = ANY(%s)")
                params.append(subs)

            if keywords := filters.get("item_keywords"):
                or_parts = ["i.name ILIKE %s" for _ in keywords]
                where.append(f"({' OR '.join(or_parts)})")
                params.extend([f"%{kw}%" for kw in keywords])

        query = f"""
            SELECT
                r.store_name,
                r.payment_method,
                r.receipt_number,
                r.purchasing_date::text AS purchasing_date,
                r.total::float8 AS total,
                r.created_at::text AS created_at,
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
            WHERE {" AND ".join(where)}
            GROUP BY r.id
            ORDER BY r.purchasing_date DESC, r.created_at DESC
            {f"LIMIT {int(filters['limit'])}" if filters and filters.get('limit') else ""}
        """

        results = self._execute(query, tuple(params), fetch="all")
        for r in results:
            if isinstance(r.get("items"), str):
                r["items"] = json.loads(r["items"])
        return results

    def delete_receipt(self, user_id: str, receipt_id: str) -> bool:
        return self._execute(
            "DELETE FROM receipts WHERE user_id = %s AND id = %s",
            (user_id, receipt_id),
        )

    def delete_last_uploaded_receipt(self, user_id: str) -> str | None:
        result = self._execute("""
            DELETE FROM receipts
            WHERE user_id = %s
              AND id = (SELECT id FROM receipts WHERE user_id = %s ORDER BY created_at DESC LIMIT 1)
            RETURNING image_url
        """, (user_id, user_id), fetch="one",)

        return result and result.get("image_url")

    def delete_all_receipts(self, user_id: str) -> list[str]:
        results = self._execute(
            "DELETE FROM receipts WHERE user_id = %s RETURNING image_url",
            (user_id,),
            fetch="all",
        )

        return [r["image_url"] for r in results if r.get("image_url")]

    def count_user_receipts(self, user_id: str) -> int:
        result = self._execute(
            "SELECT COUNT(*) AS count FROM receipts WHERE user_id = %s",
            (user_id,),
            fetch="one",
        )
        return result["count"] if result else 0
