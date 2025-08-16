"""
Storage Service
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from config import DYNAMODB_TABLE_NAME, setup_logging
from provider_factory import ProviderFactory
from receipt_schemas import ReceiptData
from pydantic import ValidationError

setup_logging()
logger = logging.getLogger(__name__)

class StorageService:
    """Service for storage operations using storage providers"""

    def __init__(self):
        # Use factory to create storage providers
        self.image_storage = ProviderFactory.create_image_storage('s3')
        self.receipt_storage = ProviderFactory.create_document_storage('dynamodb')
        self.table_name = DYNAMODB_TABLE_NAME

    def store_raw_image(self, receipt_id: str, image_data: bytes) -> Optional[str]:
        """Store receipt image using ImageStorage provider"""
        try:
            timestamp = datetime.now(timezone.utc).strftime('%Y/%m/%d')
            s3_key = f"receipts/{timestamp}/{receipt_id}.jpg"

            metadata = {
                'receipt_id': receipt_id,
                'uploaded_at': datetime.now(timezone.utc).isoformat()
            }

            return self.image_storage.store(s3_key, image_data, metadata)

        except Exception as e:
            logger.error(f"Image storage error: {e}")
            return None

    def store_receipt_data(self, receipt_id: str, secure_user_id: str, receipt_data: ReceiptData,
                      image_url: str, metadata: Optional[Dict] = None) -> bool:
        """Store receipt data using DocumentStorage provider"""

        # Prepare item - direct access to Pydantic fields
        item = {
            'user_id': secure_user_id,
            'receipt_id': receipt_id,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'image_url': image_url,
            'store_name': receipt_data.store_name,
            'payment_method': receipt_data.payment_method,
            'receipt_number': receipt_data.receipt_number,
            'total': receipt_data.total,
            'items': [item.model_dump() for item in receipt_data.items],
            'date': receipt_data.date
        }

        # Add metadata if provided
        if metadata:
            item['metadata'] = metadata

        # Remove None values (only receipt_number can be None)
        item = {k: v for k, v in item.items() if v is not None}

        try:
            return self.receipt_storage.put(self.table_name, item)

        except Exception as e:
            logger.error(f"Receipt data storage error: {e}")
            return False

    def get_filtered_receipts(self, query_plan: Dict, secure_user_id: str) -> List[ReceiptData]:
        """Get filtered receipts using DocumentStorage provider"""

        filter_params = query_plan.get("filter", {})
        receipts = []

        # Check if we can use an index for efficient querying
        if "payment_methods" in filter_params and filter_params["payment_methods"]:
            receipts = self._query_by_payment_methods(secure_user_id, filter_params["payment_methods"])

        elif "date_range" in filter_params:
            receipts = self._query_by_date_range(secure_user_id, filter_params["date_range"])

        elif "store_names" in filter_params and filter_params["store_names"]:
            receipts = self._query_by_store_names(secure_user_id, filter_params["store_names"])

        else:
            # Fall back to scanning all user receipts
            receipts = self._scan_user_receipts(secure_user_id)

        # Apply additional filters
        receipts = self._apply_additional_filters(receipts, filter_params)

        pydantic_receipts = []
        for receipt_dict in receipts:
            # Extract the receipt data from storage format
            pydantic_receipts.append(ReceiptData(**receipt_dict))

        logger.info(f"Found {len(pydantic_receipts)} receipts for user {secure_user_id}")
        return pydantic_receipts

    def delete_last_uploaded_receipt(self, secure_user_id: str) -> Optional[Dict]:
        """Delete the most recently uploaded receipt for a user"""
        try:
            # Get all receipts for user
            receipts = self.receipt_storage.query(
                table=self.table_name,
                key_condition={
                    'partition_key': {'name': 'user_id', 'value': secure_user_id}
                }
            )

            if not receipts:
                return None

            # Sort by created_at to get most recent
            sorted_receipts = sorted(
                receipts,
                key=lambda x: x.get('created_at', '1900-01-01T00:00:00'),
                reverse=True
            )

            last_receipt = sorted_receipts[0]
            receipt_id = last_receipt['receipt_id']

            # Delete from storage
            success = self.receipt_storage.delete(
                table=self.table_name,
                key={'user_id': secure_user_id, 'receipt_id': receipt_id}
            )

            if success:
                # Delete image using storage provider abstraction
                image_url = last_receipt.get('image_url')
                if image_url:
                    self._delete_receipt_image(image_url)

                logger.info(f"Deleted most recent receipt: {receipt_id}")
                return last_receipt

            return None

        except Exception as e:
            logger.error(f"Delete last receipt error: {e}")
            return None

    def delete_all_receipts(self, secure_user_id: str) -> int:
        """Delete all receipts for a user"""
        try:
            # Get all receipts for user
            receipts = self.receipt_storage.query(
                table=self.table_name,
                key_condition={
                    'partition_key': {'name': 'user_id', 'value': secure_user_id}
                }
            )

            if not receipts:
                return 0

            deleted_count = 0

            # Delete each receipt
            for receipt in receipts:
                success = self.receipt_storage.delete(
                    table=self.table_name,
                    key={'user_id': secure_user_id, 'receipt_id': receipt['receipt_id']}
                )

                if success:
                    # Delete image using storage provider abstraction
                    image_url = receipt.get('image_url')
                    if image_url:
                        self._delete_receipt_image(image_url)

                    deleted_count += 1

            logger.info(f"Deleted {deleted_count} receipts for user: {secure_user_id}")
            return deleted_count

        except Exception as e:
            logger.error(f"Delete all receipts error: {e}")
            return 0

    def count_user_receipts(self, secure_user_id: str) -> int:
        """Count total receipts for a user"""
        try:
            receipts = self.receipt_storage.query(
                table=self.table_name,
                key_condition={
                    'partition_key': {'name': 'user_id', 'value': secure_user_id}
                }
            )

            count = len(receipts)
            logger.info(f"User {secure_user_id} has {count} receipts")
            return count

        except Exception as e:
            logger.error(f"Count user receipts error: {e}")
            return 0

    def _delete_receipt_image(self, image_url: str) -> bool:
        """Delete receipt image using storage provider abstraction"""
        try:
            if not image_url:
                return False

            # Extract storage key from URL - make this provider-agnostic
            storage_key = self._extract_storage_key(image_url)
            if storage_key:
                return self.image_storage.delete(storage_key)

            return False

        except Exception as e:
            logger.error(f"Image deletion error: {e}")
            return False

    def _extract_storage_key(self, storage_url: str) -> Optional[str]:
        """Extract storage key from URL in a provider-agnostic way"""
        try:
            # Handle different URL formats
            if storage_url.startswith('s3://'):
                # S3 format: s3://bucket/key
                parts = storage_url[5:].split('/', 1)
                return parts[1] if len(parts) == 2 else None
            elif storage_url.startswith('https://'):
                # Could be S3 HTTPS URL or other cloud storage
                # This would need specific parsing logic based on provider
                return None
            else:
                # Assume it's already a key
                return storage_url

        except Exception as e:
            logger.error(f"Storage key extraction error: {e}")
            return None

    def _query_by_date_range(self, secure_user_id: str, date_range: Dict) -> List[Dict]:
        """Query receipts by date range using storage provider"""
        try:
            start_date = date_range.get("start")
            end_date = date_range.get("end")

            if not start_date or not end_date:
                return self._scan_user_receipts(secure_user_id)

            return self.receipt_storage.query_by_date_range(
                table=self.table_name,
                user_id=secure_user_id,
                start_date=start_date,
                end_date=end_date
            )

        except Exception as e:
            logger.error(f"Date range query error: {e}")
            return self._scan_user_receipts(secure_user_id)

    def _query_by_store_names(self, secure_user_id: str, store_names: List[str]) -> List[Dict]:
        """Query receipts by store names using storage provider"""
        try:
            return self.receipt_storage.query_by_stores(
                table=self.table_name,
                user_id=secure_user_id,
                store_names=store_names
            )

        except Exception as e:
            logger.error(f"Store name query error: {e}")
            return self._scan_user_receipts(secure_user_id)

    def _query_by_payment_methods(self, secure_user_id: str, payment_methods: List[str]) -> List[Dict]:
        """Query receipts by payment methods using storage provider"""
        try:
            return self.receipt_storage.query_by_payment_methods(
                table=self.table_name,
                user_id=str(secure_user_id),  # Ensure string
                payment_methods=payment_methods
            )

        except Exception as e:
            logger.error(f"Payment method query error: {e}")
            return self._scan_user_receipts(secure_user_id)

    def _scan_user_receipts(self, secure_user_id: str) -> List[Dict]:
        """Scan all receipts for a user using storage provider"""
        try:
            return self.receipt_storage.query_user_receipts(
                table=self.table_name,
                user_id=secure_user_id
            )

        except Exception as e:
            logger.error(f"User receipts scan error: {e}")
            return []

    def _apply_additional_filters(self, receipts: List[Dict], filters: Dict) -> List[Dict]:
        """Apply additional filters to receipts"""
        # Keep your existing implementation
        try:
            filtered_receipts = receipts

            price_range = filters.get("price_range")
            if price_range and isinstance(price_range, dict):
                min_price = price_range.get("min")
                max_price = price_range.get("max")

                if min_price is not None and max_price is not None:
                    try:
                        min_price = float(min_price)
                        max_price = float(max_price)

                        filtered_receipts = [
                            receipt for receipt in filtered_receipts
                            if min_price <= float(receipt.get('total', 0)) <= max_price
                        ]
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Invalid price range values: {price_range}, error: {e}")

            return filtered_receipts

        except Exception as e:
            logger.error(f"Additional filter error: {e}")
            return receipts

    def _delete_raw_image(self, s3_url: str) -> bool:
        """Delete image from image storage using storage provider"""
        try:
            # Extract key from s3://bucket/key format
            if s3_url.startswith('s3://'):
                parts = s3_url[5:].split('/', 1)
                if len(parts) == 2:
                    s3_key = parts[1]
                    return self.image_storage.delete(s3_key)

            return False

        except Exception as e:
            logger.error(f"raw image delete error: {e}")
            return False
