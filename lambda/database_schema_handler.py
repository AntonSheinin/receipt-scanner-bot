"""
Database Schema Creation Lambda Handler
"""

import json
import psycopg2
import boto3
import urllib3
import logging


logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """Handle database schema creation for CloudFormation custom resource"""

    logger.info(f"Event: {json.dumps(event, default=str)}")

    request_type = event['RequestType']

    if request_type == 'Create':
        try:
            create_database_schema(event)
            send_response(event, context, "SUCCESS", {"Message": "Schema created successfully"})

        except Exception as e:
            logger.error(f"Error creating schema: {str(e)}")
            send_response(event, context, "FAILED", {"Error": str(e)})
    else:
        # For Update/Delete, just return success
        logger.info(f"No action needed for {request_type}")
        send_response(event, context, "SUCCESS", {"Message": f"No action needed for {request_type}"})


def create_database_schema(event):
    """Create database tables and indexes"""

    # Get database credentials from Secrets Manager
    secret_arn = event['ResourceProperties']['SecretArn']

    secrets_client = boto3.client('secretsmanager')
    secret_response = secrets_client.get_secret_value(SecretId=secret_arn)
    secret = json.loads(secret_response['SecretString'])

    logger.info(f"Connecting to database: {secret['host']}:{secret['port']}")

    # Connect to database
    conn = psycopg2.connect(
        host=secret['host'],
        port=secret['port'],
        database=secret['dbname'],
        user=secret['username'],
        password=secret['password']
    )

    cursor = conn.cursor()

    try:
        # Create receipts table
        logger.info("Creating receipts table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS receipts (
                id UUID PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                store_name VARCHAR(100),
                date DATE,
                total DECIMAL(10,2),
                payment_method VARCHAR(20),
                receipt_number VARCHAR(50),
                image_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create receipt_items table
        logger.info("Creating receipt_items table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS receipt_items (
                id UUID PRIMARY KEY,
                receipt_id UUID NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
                name VARCHAR(200) NOT NULL,
                price DECIMAL(10,2) NOT NULL,
                quantity DECIMAL(8,3) NOT NULL DEFAULT 1,
                category VARCHAR(50),
                subcategory VARCHAR(50),
                discount DECIMAL(10,2) DEFAULT 0
            )
        """)

        # Create indexes for performance
        logger.info("Creating indexes...")

        # Receipts indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_receipts_user_id ON receipts(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts(date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_receipts_user_date ON receipts(user_id, date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_receipts_store ON receipts(store_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_receipts_payment ON receipts(payment_method)')

        # Items indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_items_receipt_id ON receipt_items(receipt_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_items_category ON receipt_items(category)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_items_subcategory ON receipt_items(subcategory)')

        # Full-text search index for Hebrew item names
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_items_name_fts ON receipt_items USING gin(to_tsvector(\'simple\', name))')

        conn.commit()
        logger.info("Database schema created successfully")

    finally:
        cursor.close()
        conn.close()


def send_response(event, context, status, data):
    """Send response back to CloudFormation"""

    response_body = {
        'Status': status,
        'Reason': f'See CloudWatch Log Stream: {context.log_stream_name}',
        'PhysicalResourceId': context.log_stream_name,
        'StackId': event['StackId'],
        'RequestId': event['RequestId'],
        'LogicalResourceId': event['LogicalResourceId'],
        'Data': data
    }

    json_response = json.dumps(response_body)
    logger.info(f"Sending response: {json_response}")

    try:
        http = urllib3.PoolManager()
        response = http.request(
            'PUT',
            event['ResponseURL'],
            body=json_response,
            headers={
                'content-type': '',
                'content-length': str(len(json_response))
            }
        )
        logger.info(f"CloudFormation response status: {response.status}")

    except Exception as e:
        logger.error(f"Failed to send response to CloudFormation: {e}")
        raise
