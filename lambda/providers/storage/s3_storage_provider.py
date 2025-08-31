"""
    S3 Storage Provider module
"""

import boto3
import logging
from typing import Optional, Dict
from datetime import datetime, timezone
from provider_interfaces import ImageStorage
from config import get_s3_client, S3_BUCKET_NAME, setup_logging


setup_logging()
logger = logging.getLogger(__name__)

class S3StorageProvider(ImageStorage):
    """S3 implementation of ImageStorage interface"""

    def __init__(self):
        self.s3_client = get_s3_client()
        self.bucket_name = S3_BUCKET_NAME

    def store(self, key: str, image_data: bytes, metadata: Optional[Dict] = None) -> Optional[str]:
        """Store image in S3"""
        try:
            if not self.bucket_name:
                logger.error("S3 bucket name not configured")
                return None

            # Prepare metadata
            s3_metadata = {
                'uploaded_at': datetime.now(timezone.utc).isoformat()
            }
            if metadata:
                s3_metadata.update(metadata)

            # Store in S3
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=image_data,
                ContentType='image/jpeg',
                Metadata=s3_metadata
            )

            s3_url = f"s3://{self.bucket_name}/{key}"
            logger.info(f"Image stored: {s3_url}")
            return s3_url

        except Exception as e:
            logger.error(f"S3 storage error: {e}")
            return None

    def retrieve(self, key: str) -> Optional[bytes]:
        """Retrieve image from S3"""
        try:
            if not self.bucket_name:
                return None

            response = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=key
            )
            return response['Body'].read()

        except Exception as e:
            logger.error(f"S3 retrieval error: {e}")
            return None

    def delete(self, key: str) -> bool:
        """Delete image from S3"""
        try:
            if not self.bucket_name:
                return False

            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=key
            )

            logger.info(f"Deleted S3 image: {key}")
            return True

        except Exception as e:
            logger.error(f"S3 delete error: {e}")
            return False

    def exists(self, key: str) -> bool:
        """Check if image exists in S3"""
        try:
            if not self.bucket_name:
                return False

            self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=key
            )
            return True

        except Exception:
            return False

    def generate_url(self, key: str, expires_in: int = 3600) -> Optional[str]:
        """Generate presigned URL for S3 object"""
        try:
            if not self.bucket_name:
                return None

            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': key},
                ExpiresIn=expires_in
            )
            return url

        except Exception as e:
            logger.error(f"S3 URL generation error: {e}")
            return None
