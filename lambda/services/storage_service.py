"""
Storage Service - S3 and DynamoDB Operations
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict

from config import get_s3_client, get_receipts_table, S3_BUCKET_NAME
from utils.helpers import convert_decimals

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
        """Store receipt data in DynamoDB"""
        try:
            if not self.receipts_table:
                logger.error("DynamoDB table not configured")
                return False
            
            item = {
                'receipt_id': receipt_id,
                'user_id': user_id,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'image_url': image_url,
                'store_name': receipt_data.get('store_name'),
                'date': receipt_data.get('date'),
                'receipt_number': receipt_data.get('receipt_number'),
                'total': receipt_data.get('total'),
                'items': receipt_data.get('items', []),
                'raw_data': receipt_data
            }
            
            # Remove None values
            item = {k: v for k, v in item.items() if v is not None}
            self.receipts_table.put_item(Item=item)
            
            logger.info(f"Receipt stored: {receipt_id}")
            return True
            
        except Exception as e:
            logger.error(f"DynamoDB storage error: {e}")
            return False
    
    def get_filtered_receipts(self, query_plan: Dict, user_id: str) -> List[Dict]:
        """Get filtered receipts from DynamoDB"""
        try:
            if not self.receipts_table:
                logger.error("DynamoDB table not configured")
                return []
            
            # Build DynamoDB filter
            filter_expressions = ["user_id = :user_id"]
            expression_values = {":user_id": user_id}
            
            filter_params = query_plan.get("filter", {})
            
            # Date range filter
            if "date_range" in filter_params:
                filter_expressions.append("created_at BETWEEN :start_date AND :end_date")
                expression_values[":start_date"] = filter_params["date_range"]["start"] + "T00:00:00"
                expression_values[":end_date"] = filter_params["date_range"]["end"] + "T23:59:59"
            
            # Store name filter
            if "store_names" in filter_params and filter_params["store_names"]:
                store_conditions = []
                for i, store in enumerate(filter_params["store_names"]):
                    store_conditions.append(f"contains(store_name, :store_{i})")
                    expression_values[f":store_{i}"] = store
                filter_expressions.append(f"({' OR '.join(store_conditions)})")
            
            # Execute DynamoDB scan
            response = self.receipts_table.scan(
                FilterExpression=" AND ".join(filter_expressions),
                ExpressionAttributeValues=expression_values
            )
            
            receipts = convert_decimals(response.get('Items', []))
            logger.info(f"Found {len(receipts)} receipts from DynamoDB")
            
            return receipts
            
        except Exception as e:
            logger.error(f"DynamoDB query error: {e}")
            return []