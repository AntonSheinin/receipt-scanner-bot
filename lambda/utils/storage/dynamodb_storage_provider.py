import boto3
import logging
from typing import Optional, Dict, List, Any
from boto3.dynamodb.conditions import Key, Attr
from interfaces import DocumentStorage
from config import get_dynamodb, setup_logging
from utils.helpers import convert_floats_to_decimals, convert_decimals_to_floats

setup_logging()
logger = logging.getLogger(__name__)

class DynamoDBStorageProvider(DocumentStorage):
    """DynamoDB implementation of DocumentStorage interface"""
    
    def __init__(self):
        self.dynamodb = get_dynamodb()
    
    def put(self, table: str, item: Dict[str, Any]) -> bool:
        """Store document in DynamoDB"""
        try:
            table_resource = self.dynamodb.Table(table)
            
            # Convert floats to Decimal for DynamoDB
            processed_item = convert_floats_to_decimals(item)
            
            table_resource.put_item(Item=processed_item)
            
            logger.info(f"Document stored in table: {table}")
            return True
            
        except Exception as e:
            logger.error(f"DynamoDB put error: {e}")
            return False
    
    def get(self, table: str, key: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Retrieve document from DynamoDB"""
        try:
            table_resource = self.dynamodb.Table(table)
            
            response = table_resource.get_item(Key=key)
            
            if 'Item' in response:
                # Convert Decimal back to float
                return convert_decimals_to_floats(response['Item'])
            
            return None
            
        except Exception as e:
            logger.error(f"DynamoDB get error: {e}")
            return None
    
    def query(self, table: str, key_condition: Dict[str, Any], 
              filter_expression: Optional[Dict] = None,
              index_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Query documents from DynamoDB"""
        try:
            table_resource = self.dynamodb.Table(table)
            
            # Build query parameters
            query_params = {
                'KeyConditionExpression': self._build_key_condition(key_condition)
            }
            
            if index_name:
                query_params['IndexName'] = index_name
            
            if filter_expression:
                query_params['FilterExpression'] = self._build_filter_expression(filter_expression)
            
            response = table_resource.query(**query_params)
            
            # Convert Decimal back to float
            return convert_decimals_to_floats(response.get('Items', []))
            
        except Exception as e:
            logger.error(f"DynamoDB query error: {e}")
            return []
    
    def scan(self, table: str, filter_expression: Optional[Dict] = None,
             limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Scan documents from DynamoDB"""
        try:
            table_resource = self.dynamodb.Table(table)
            
            scan_params = {}
            
            if filter_expression:
                scan_params['FilterExpression'] = self._build_filter_expression(filter_expression)
            
            if limit:
                scan_params['Limit'] = limit
            
            response = table_resource.scan(**scan_params)
            
            # Convert Decimal back to float
            return convert_decimals_to_floats(response.get('Items', []))
            
        except Exception as e:
            logger.error(f"DynamoDB scan error: {e}")
            return []
    
    def delete(self, table: str, key: Dict[str, Any]) -> bool:
        """Delete document from DynamoDB"""
        try:
            table_resource = self.dynamodb.Table(table)
            
            table_resource.delete_item(Key=key)
            
            logger.info(f"Document deleted from table: {table}")
            return True
            
        except Exception as e:
            logger.error(f"DynamoDB delete error: {e}")
            return False
    
    def batch_write(self, table: str, items: List[Dict[str, Any]]) -> bool:
        """Batch write documents to DynamoDB"""
        try:
            table_resource = self.dynamodb.Table(table)
            
            with table_resource.batch_writer() as batch:
                for item in items:
                    processed_item = convert_floats_to_decimals(item)
                    batch.put_item(Item=processed_item)
            
            logger.info(f"Batch wrote {len(items)} items to table: {table}")
            return True
            
        except Exception as e:
            logger.error(f"DynamoDB batch write error: {e}")
            return False
    
    def _build_key_condition(self, key_condition: Dict[str, Any]):
        """Build DynamoDB key condition expression"""
        # Simple implementation - can be enhanced
        if 'partition_key' in key_condition:
            condition = Key(key_condition['partition_key']['name']).eq(key_condition['partition_key']['value'])
            
            if 'sort_key' in key_condition:
                sort_condition = key_condition['sort_key']
                if sort_condition['operator'] == 'eq':
                    condition = condition & Key(sort_condition['name']).eq(sort_condition['value'])
                elif sort_condition['operator'] == 'between':
                    condition = condition & Key(sort_condition['name']).between(
                        sort_condition['start'], sort_condition['end']
                    )
            
            return condition
        
        return None
    
    def _build_filter_expression(self, filter_expr: Dict[str, Any]):
        """Build DynamoDB filter expression"""
        # Simple implementation - can be enhanced
        if 'attribute' in filter_expr and 'value' in filter_expr:
            return Attr(filter_expr['attribute']).eq(filter_expr['value'])
        
        return None