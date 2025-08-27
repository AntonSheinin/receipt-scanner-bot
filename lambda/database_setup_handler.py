"""
Database Setup Lambda Handler
Creates both databases and their schemas
"""

import os
import json
import psycopg
import urllib3
import logging


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """Handle database and schema creation for CloudFormation custom resource"""

    logger.info(f"Database setup event: {event.get('RequestType')}")

    if event['RequestType'] == 'Create':
        try:
            setup_databases()
            send_response(event, context, "SUCCESS", {"Message": "Databases and schemas created"})
        except Exception as e:
            logger.error(f"Setup failed: {e}")
            send_response(event, context, "FAILED", {"Error": str(e)})
    else:
        # For Update/Delete, no action needed
        send_response(event, context, "SUCCESS", {"Message": "No action required"})


def setup_databases():
    """Create databases and schemas in single operation"""

    # Get connection info
    db_host = os.getenv('DB_HOST')
    db_user = os.getenv('DB_USER')
    db_password = os.getenv('DB_PASSWORD')
    db_port = int(os.getenv('DB_PORT', 5432))

    logger.info(f"Setting up databases on {db_host}")

    # Connect to default postgres database
    conn_string = f"host={db_host} port={db_port} dbname=postgres user={db_user} password={db_password}"

    with psycopg.connect(conn_string, autocommit=True) as conn:
        with conn.cursor() as cursor:
            # Create both databases
            for db_name in ['receipt_scanner_dev', 'receipt_scanner_prod']:
                cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
                if not cursor.fetchone():
                    cursor.execute(f"CREATE DATABASE {db_name}")
                    logger.info(f"Created database: {db_name}")
                else:
                    logger.info(f"Database exists: {db_name}")

    # Create schemas in both databases
    for db_name in ['receipt_scanner_dev', 'receipt_scanner_prod']:
        create_schema(db_host, db_port, db_name, db_user, db_password)


def create_schema(host, port, database, user, password):
    """Create tables and indexes in specified database"""

    conn_string = f"host={host} port={port} dbname={database} user={user} password={password}"

    with psycopg.connect(conn_string) as conn:
        with conn.cursor() as cursor:

            # Create tables
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS receipts (
                    id UUID PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    store_name VARCHAR(100),
                    purchasing_date DATE,
                    total DECIMAL(10,2),
                    payment_method VARCHAR(20),
                    receipt_number VARCHAR(50),
                    image_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS receipt_items (
                    id UUID PRIMARY KEY,
                    receipt_id UUID NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
                    name VARCHAR(200) NOT NULL,
                    price DECIMAL(10,2) NOT NULL,
                    quantity DECIMAL(8,3) NOT NULL DEFAULT 1,
                    category VARCHAR(50),
                    subcategory VARCHAR(50),
                    discount DECIMAL(10,2) DEFAULT 0
                );
            """)

            # Create indexes
            indexes = [
                'CREATE INDEX IF NOT EXISTS idx_receipts_user_id ON receipts(user_id)',
                'CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts(purchasing_date)',
                'CREATE INDEX IF NOT EXISTS idx_receipts_user_date ON receipts(user_id, purchasing_date)',
                'CREATE INDEX IF NOT EXISTS idx_receipts_store ON receipts(store_name)',
                'CREATE INDEX IF NOT EXISTS idx_items_receipt_id ON receipt_items(receipt_id)',
                'CREATE INDEX IF NOT EXISTS idx_items_category ON receipt_items(category)',
                'CREATE INDEX IF NOT EXISTS idx_items_name_fts ON receipt_items USING gin(to_tsvector(\'simple\', name))'
            ]

            for index_sql in indexes:
                cursor.execute(index_sql)

            conn.commit()
            logger.info(f"Schema created in {database}")


def send_response(event, context, status, data):
    """Send CloudFormation response"""

    response = {
        'Status': status,
        'PhysicalResourceId': context.log_stream_name,
        'StackId': event['StackId'],
        'RequestId': event['RequestId'],
        'LogicalResourceId': event['LogicalResourceId'],
        'Data': data
    }

    try:
        http = urllib3.PoolManager()
        http.request('PUT', event['ResponseURL'],
                    body=json.dumps(response),
                    headers={'content-type': '', 'content-length': str(len(json.dumps(response)))})
        logger.info("CloudFormation response sent")
    except Exception as e:
        logger.error(f"Failed to send response: {e}")
        raise
