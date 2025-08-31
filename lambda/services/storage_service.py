"""
    Storage Service module
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from config import setup_logging
from providers.provider_factory import ProviderFactory
from receipt_schemas import ReceiptData


setup_logging()
logger = logging.getLogger(__name__)

class StorageService:
    """Business logic layer for storage operations"""

    def __init__(self):
        self.image_storage = ProviderFactory.create_image_storage('s3')
        self.document_storage = ProviderFactory.create_document_storage('postgresql')

    # --------------------Image Storage Methods--------------------------

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

    def delete_receipt_image(self, image_url: str) -> bool:
        """Delete receipt image"""
        try:
            if not image_url:
                return False

            # Extract storage key from URL
            storage_key = self._extract_storage_key(image_url)
            if storage_key:
                return self.image_storage.delete(storage_key)

            return False

        except Exception as e:
            logger.error(f"Image deletion error: {e}")
            return False

    def _extract_storage_key(self, storage_url: str) -> Optional[str]:
        """Extract storage key from URL"""
        try:
            if storage_url.startswith('s3://'):
                parts = storage_url[5:].split('/', 1)
                return parts[1] if len(parts) == 2 else None
            else:
                return storage_url

        except Exception as e:
            logger.error(f"Storage key extraction error: {e}")
            return None

    # ------------------Receipt Storage Methods--------------------------------------

    def store_receipt_data(self, receipt_id: str, user_id: str, receipt_data: ReceiptData,
                          image_url: str, metadata: Optional[Dict] = None) -> bool:
        """Store receipt data with business logic validation"""

        receipt_dict = receipt_data.model_dump()
        receipt_dict.update({
            'receipt_id': receipt_id,
            'user_id': user_id,
            'image_url': image_url
        })

        try:
            return self.document_storage.save_receipt_with_items(user_id, receipt_dict)

        except ValueError as e:
            if str(e) == "DUPLICATE_RECEIPT":
                raise  # Re-raise to be handled by caller
            logger.error(f"Receipt storage validation error: {e}")
            return False

        except Exception as e:
            logger.error(f"Receipt storage error: {e}")
            return False

    def get_filtered_receipts(self, query_plan: Dict, user_id: str) -> List[Dict[str, Any]]:
        """Get filtered receipts with business logic"""

        filters = query_plan.get("filter", {})

        provider_filters = self._prepare_filters_for_provider(filters)

        try:
            receipts = self.document_storage.get_filtered_receipts(user_id, provider_filters)

            logger.info(f"Found {len(receipts)} receipts for user {user_id[:8]}...")
            return receipts

        except Exception as e:
            logger.error(f"Get filtered receipts error: {e}")
            return []

    def delete_last_uploaded_receipt(self, user_id: str) -> bool:
        """Delete most recent receipt using SQL efficiently"""

        try:
            image_url = self.document_storage.delete_last_uploaded_receipt(user_id)

            if image_url:
                self.delete_receipt_image(image_url)
                logger.info(f"Deleted last receipt and image for user: {user_id}")
                return True

            else:
                logger.info(f"No receipts found to delete for user: {user_id}")
                return False

        except Exception as e:
            logger.error(f"Delete last receipt error: {e}")
            return False

    def delete_all_receipts(self, user_id: str) -> int:
        """Delete all receipts using SQL efficiently"""

        try:
            image_urls = self.document_storage.delete_all_receipts(user_id)

            for image_url in image_urls:
                self.delete_receipt_image(image_url)

            deleted_count = len(image_urls)

            logger.info(f"Deleted {deleted_count} receipts for user: {user_id}")
            return deleted_count

        except Exception as e:
            logger.error(f"Delete all receipts error: {e}")
            return 0

    def count_user_receipts(self, user_id: str) -> int:
        """Count user receipts using SQL efficiently"""

        try:
            count = self.document_storage.count_user_receipts(user_id)

            logger.info(f"User {user_id} has {count} receipts")

            return count

        except Exception as e:
            logger.error(f"Count receipts error: {e}")
            return 0

    def _prepare_filters_for_provider(self, domain_filters: Dict) -> Dict:
        """Transform domain filters to provider format"""

        possible_filters = ['date_range', 'store_names', 'categories', 'subcategories', 'item_keywords', 'payment_methods', 'price_range', 'limit']
        provider_filters = {}

        for key in possible_filters:
            if key in domain_filters:
                provider_filters[key] = domain_filters[key]

        if 'store_names' in provider_filters:
            provider_filters['store_names'] = [store.strip() for store in provider_filters['store_names']]

        if 'date_range' in provider_filters:
            date_range = provider_filters['date_range']
            if date_range.get('start') and date_range.get('end'):
                if date_range['start'] > date_range['end']:
                    logger.warning("Invalid date range: start > end, swapping")
                    provider_filters['date_range'] = {
                        'start': date_range['end'],
                        'end': date_range['start']
                    }

        return provider_filters
