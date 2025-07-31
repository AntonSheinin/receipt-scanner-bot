"""
Storage Service - S3 and DynamoDB Operations
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict
from boto3.dynamodb.conditions import Key, Attr

from config import get_s3_client, get_receipts_table, S3_BUCKET_NAME, setup_logging
from utils.helpers import convert_decimals_to_floats, convert_floats_to_decimals


setup_logging()
logger = logging.getLogger(__name__)

class StorageService:
    """Service for S3 and DynamoDB operations"""
    
    def __init__(self):
        self.s3_client = get_s3_client()
        self.receipts_table = get_receipts_table()
    
    def store_image(self, receipt_id: str, image_data: bytes) -> Optional[str]:
        """Store receipt image in S3"""
        try:
            if not S3_BUCKET_NAME:
                logger.error("S3 bucket name not configured")
                return None
            
            timestamp = datetime.now(timezone.utc).strftime('%Y/%m/%d')
            s3_key = f"receipts/{timestamp}/{receipt_id}.jpg"
            
            self.s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=s3_key,
                Body=image_data,
                ContentType='image/jpeg',
                Metadata={
                    'receipt_id': receipt_id,
                    'uploaded_at': datetime.now(timezone.utc).isoformat()
                }
            )
            
            s3_url = f"s3://{S3_BUCKET_NAME}/{s3_key}"
            logger.info(f"Image stored: {s3_url}")
            return s3_url
            
        except Exception as e:
            logger.error(f"S3 storage error: {e}")
            return None
    
    def store_receipt_data(self, receipt_id: str, user_id: str, receipt_data: Dict, image_url: str) -> bool:
        """Store receipt data in DynamoDB with duplicate prevention"""
        try:
            if not self.receipts_table:
                logger.error("DynamoDB table not configured")
                return False
            
            # Check if receipt already exists
            try:
                existing = self.receipts_table.get_item(
                    Key={'user_id': user_id, 'receipt_id': receipt_id}
                )
                if 'Item' in existing:
                    logger.info(f"Receipt {receipt_id} already exists, skipping storage")
                    return True  # Return success since it's already stored
            except Exception as e:
                logger.warning(f"Error checking for existing receipt: {e}")
            
            # Convert all numeric values to Decimal for DynamoDB
            processed_data = convert_floats_to_decimals(receipt_data)
            
            item = {
                'user_id': user_id,
                'receipt_id': receipt_id,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'image_url': image_url,
                'store_name': processed_data.get('store_name', ''),
                'date': processed_data.get('date', ''),
                'receipt_number': processed_data.get('receipt_number'),
                'payment_method': processed_data.get('payment_method'),
                'total': processed_data.get('total'),
                'items': processed_data.get('items', []),
                'raw_data': processed_data
            }
            
            # Remove None values
            item = {k: v for k, v in item.items() if v is not None}
            
            # Use conditional put to prevent overwriting
            self.receipts_table.put_item(
                Item=item,
                ConditionExpression='attribute_not_exists(receipt_id)'
            )
            
            logger.info(f"Receipt stored: {receipt_id}")
            return True
            
        except Exception as e:
            if 'ConditionalCheckFailedException' in str(e):
                logger.info(f"Receipt {receipt_id} already exists (conditional check failed)")
                return True  # Already exists, that's fine
            logger.error(f"DynamoDB storage error: {e}")
            return False
    
    def get_filtered_receipts(self, query_plan: Dict, user_id: str) -> List[Dict]:
        """Get filtered receipts from DynamoDB"""
        try:
            if not self.receipts_table:
                logger.error("DynamoDB table not configured")
                return []
            
            filter_params = query_plan.get("filter", {})
            receipts = []
            
            # Check if we can use an index for efficient querying
            if "payment_methods" in filter_params and filter_params["payment_methods"]:
                receipts = self._query_by_payment_methods(user_id, filter_params["payment_methods"])
            elif "date_range" in filter_params:
                receipts = self._query_by_date_range(user_id, filter_params["date_range"])
            elif "store_names" in filter_params and filter_params["store_names"]:
                receipts = self._query_by_store_names(user_id, filter_params["store_names"])
            else:
                # Fall back to scanning all user receipts
                receipts = self._scan_user_receipts(user_id)
            
            # Apply additional filters
            receipts = self._apply_additional_filters(receipts, filter_params)
            
            logger.info(f"Found {len(receipts)} receipts for user {user_id}")
            return receipts
            
        except Exception as e:
            logger.error(f"DynamoDB query error: {e}")
            return []
    
    def _query_by_date_range(self, user_id: str, date_range: Dict) -> List[Dict]:
        """Query receipts by date range using DateIndex"""
        try:
            start_date = date_range.get("start", "1900-01-01")
            end_date = date_range.get("end", "2099-12-31")
            
            response = self.receipts_table.query(
                IndexName="DateIndex",
                KeyConditionExpression=Key('user_id').eq(user_id) & Key('date').between(start_date, end_date)
            )
            
            return convert_decimals_to_floats(response.get('Items', []))
            
        except Exception as e:
            logger.error(f"Date range query error: {e}")
            return self._scan_user_receipts(user_id)  # Fallback
    
    def _query_by_store_names(self, user_id: str, store_names: List[str]) -> List[Dict]:
        """Query receipts by store names using StoreIndex"""
        try:
            all_receipts = []
            
            for store_name in store_names:
                response = self.receipts_table.query(
                    IndexName="StoreIndex",
                    KeyConditionExpression=Key('user_id').eq(user_id) & Key('store_name').eq(store_name),
                    FilterExpression=Attr('store_name').contains(store_name)
                )
                all_receipts.extend(response.get('Items', []))
            
            # Remove duplicates based on receipt_id
            seen_ids = set()
            unique_receipts = []
            for receipt in all_receipts:
                if receipt['receipt_id'] not in seen_ids:
                    seen_ids.add(receipt['receipt_id'])
                    unique_receipts.append(receipt)
            
            return convert_decimals_to_floats(unique_receipts)
            
        except Exception as e:
            logger.error(f"Store name query error: {e}")
            return self._scan_user_receipts(user_id)  # Fallback
        
    def _query_by_payment_methods(self, user_id: str, payment_methods: List[str]) -> List[Dict]:
        """Query receipts by payment methods using PaymentMethodIndex"""
        try:
            all_receipts = []
            
            for payment_method in payment_methods:
                response = self.receipts_table.query(
                    IndexName="PaymentMethodIndex",
                    KeyConditionExpression=Key('user_id').eq(user_id) & Key('payment_method').eq(payment_method)
                )
                all_receipts.extend(response.get('Items', []))
            
            # Remove duplicates based on receipt_id
            seen_ids = set()
            unique_receipts = []
            for receipt in all_receipts:
                if receipt['receipt_id'] not in seen_ids:
                    seen_ids.add(receipt['receipt_id'])
                    unique_receipts.append(receipt)
            
            return convert_decimals_to_floats(unique_receipts)
            
        except Exception as e:
            logger.error(f"Payment method query error: {e}")
            return self._scan_user_receipts(user_id)  # Fallback
    
    def _scan_user_receipts(self, user_id: str) -> List[Dict]:
        """Scan all receipts for a user (fallback method)"""
        try:
            response = self.receipts_table.query(
                KeyConditionExpression=Key('user_id').eq(user_id)
            )
            
            return convert_decimals_to_floats(response.get('Items', []))
            
        except Exception as e:
            logger.error(f"User receipts scan error: {e}")
            return []
    
    def _apply_additional_filters(self, receipts: List[Dict], filters: Dict) -> List[Dict]:
        """Apply additional filters to receipts"""
        try:
            filtered_receipts = receipts
            
            # Filter by price range on total
            if "price_range" in filters:
                price_range = filters["price_range"]
                min_price = price_range.get("min", 0)
                max_price = price_range.get("max", float('inf'))
                
                filtered_receipts = [
                    receipt for receipt in filtered_receipts
                    if min_price <= float(receipt.get('total', 0)) <= max_price
                ]
            
            return filtered_receipts
            
        except Exception as e:
            logger.error(f"Additional filter error: {e}")
            return receipts
        
    def delete_last_receipt(self, user_id: str) -> Optional[Dict]:
        """Delete the most recently created receipt for a user"""
        try:
            if not self.receipts_table:
                logger.error("DynamoDB table not configured")
                return None
            
            # Get the most recent receipt
            response = self.receipts_table.query(
                KeyConditionExpression=Key('user_id').eq(user_id),
                ScanIndexForward=False,  # Sort in descending order
                Limit=1
            )
            
            items = response.get('Items', [])
            if not items:
                return None
            
            last_receipt = convert_decimals_to_floats(items[0])
            receipt_id = last_receipt['receipt_id']
            
            # Delete from DynamoDB
            self.receipts_table.delete_item(
                Key={
                    'user_id': user_id,
                    'receipt_id': receipt_id
                }
            )
            
            # Delete image from S3 if exists
            image_url = last_receipt.get('image_url')
            if image_url and image_url.startswith('s3://'):
                self._delete_s3_image(image_url)
            
            logger.info(f"Deleted receipt: {receipt_id} for user: {user_id}")
            return last_receipt
            
        except Exception as e:
            logger.error(f"Delete last receipt error: {e}")
            return None

    def delete_all_receipts(self, user_id: str) -> int:
        """Delete all receipts for a user"""
        try:
            if not self.receipts_table:
                logger.error("DynamoDB table not configured")
                return 0
            
            # Get all receipts for the user
            response = self.receipts_table.query(
                KeyConditionExpression=Key('user_id').eq(user_id)
            )
            
            items = response.get('Items', [])
            if not items:
                return 0
            
            deleted_count = 0
            
            # Delete each receipt
            with self.receipts_table.batch_writer() as batch:
                for item in items:
                    batch.delete_item(
                        Key={
                            'user_id': user_id,
                            'receipt_id': item['receipt_id']
                        }
                    )
                    
                    # Delete image from S3 if exists
                    image_url = item.get('image_url')
                    if image_url and image_url.startswith('s3://'):
                        self._delete_s3_image(image_url)
                    
                    deleted_count += 1
            
            logger.info(f"Deleted {deleted_count} receipts for user: {user_id}")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Delete all receipts error: {e}")
            return 0

    def _delete_s3_image(self, s3_url: str) -> bool:
        """Delete image from S3"""
        try:
            if not S3_BUCKET_NAME:
                return False
            
            # Extract key from s3://bucket/key format
            s3_key = s3_url.replace(f"s3://{S3_BUCKET_NAME}/", "")
            
            self.s3_client.delete_object(
                Bucket=S3_BUCKET_NAME,
                Key=s3_key
            )
            
            logger.info(f"Deleted S3 image: {s3_key}")
            return True
            
        except Exception as e:
            logger.error(f"S3 delete error: {e}")
            return False