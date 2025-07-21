"""
Receipt Bot Stack - AWS CDK Infrastructure
"""
import os
from typing import Dict, Any
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_lambda as _lambda,
    aws_apigateway as apigateway,
    aws_iam as iam,
    aws_logs as logs,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    CfnOutput
)
from constructs import Construct
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class ReceiptBotStack(Stack):
    
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Get bot token from environment variable or CDK context (fallback)
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN') or self.node.try_get_context("telegram_bot_token")
        
        if not bot_token:
            # For bootstrap or synth, use placeholder
            bot_token = "placeholder_token_for_bootstrap"
            print("⚠️ No bot token found. Set TELEGRAM_BOT_TOKEN in .env file or use: cdk deploy -c telegram_bot_token=YOUR_TOKEN")
        else:
            print("✅ Bot token loaded successfully")
        
        # Create S3 bucket for receipt images
        receipt_bucket = self._create_s3_bucket()
        
        # Create DynamoDB table for receipt data
        receipt_table = self._create_dynamodb_table()
        
        # Create IAM role for Lambda
        lambda_role = self._create_lambda_role(receipt_bucket, receipt_table)
        
        # Create Lambda function
        telegram_lambda = self._create_telegram_lambda(lambda_role, bot_token, receipt_bucket, receipt_table)
        
        # Create API Gateway
        api_gateway = self._create_api_gateway(telegram_lambda)
        
        # Output the webhook URL
        CfnOutput(
            self,
            "TelegramWebhookUrl",
            value=f"{api_gateway.url}webhook",
            description="Telegram webhook URL to configure in BotFather"
        )
        
        # Output S3 bucket name
        CfnOutput(
            self,
            "ReceiptsBucketName",
            value=receipt_bucket.bucket_name,
            description="S3 bucket for storing receipt images"
        )
        
        # Output DynamoDB table name
        CfnOutput(
            self,
            "ReceiptsTableName", 
            value=receipt_table.table_name,
            description="DynamoDB table for storing receipt data"
        )
    
    def _create_s3_bucket(self) -> s3.Bucket:
        """Create S3 bucket for storing receipt images"""
        return s3.Bucket(
            self,
            "ReceiptImagesBucket",
            bucket_name=f"receipt-images-{self.account}-{self.region}",
            removal_policy=RemovalPolicy.DESTROY,  # For MVP - allows easy cleanup
            auto_delete_objects=True,  # For MVP - removes objects on stack deletion
            versioned=False, 
            public_read_access=False,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="DeleteOldImages",
                    enabled=True,
                    expiration=Duration.days(90)  # Auto-delete images after 90 days
                )
            ]
        )
    
    def _create_dynamodb_table(self) -> dynamodb.Table:
        """Create DynamoDB table for storing receipt data"""
        return dynamodb.Table(
            self,
            "ReceiptsTable",
            table_name="receipts",
            partition_key=dynamodb.Attribute(
                name="receipt_id",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="user_id", 
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST, 
            removal_policy=RemovalPolicy.DESTROY,  # For MVP - allows easy cleanup
            point_in_time_recovery=False  # Disable for MVP to save costs
            # Note: GSI can be added later via console if needed for querying
        )
    
    def _create_lambda_role(self, bucket: s3.Bucket, table: dynamodb.Table) -> iam.Role:
        """Create IAM role with necessary permissions for Lambda"""
        role = iam.Role(
            self,
            "TelegramLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ]
        )
        
        # Add Bedrock permissions (MVP - broad access)
        role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream"
                ],
                resources=["*"]
            )
        )
        
        # Add S3 permissions for receipt images
        bucket.grant_read_write(role)
        
        # Add DynamoDB permissions for receipt data
        table.grant_read_write_data(role)
        
        return role
    
    def _create_telegram_lambda(self, role: iam.Role, bot_token: str, bucket: s3.Bucket, table: dynamodb.Table) -> _lambda.Function:
        """Create Lambda function for Telegram webhook handling"""
        
        # Create log group first
        log_group = logs.LogGroup(
            self,
            "TelegramHandlerLogGroup",
            log_group_name="/aws/lambda/TelegramHandler",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY
        )
        
        return _lambda.Function(
            self,
            "TelegramHandler",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="telegram_handler.lambda_handler",
            code=_lambda.Code.from_asset(
                "lambda",
                bundling=cdk.BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash", "-c",
                        "pip install -r requirements.txt -t /asset-output && cp -r . /asset-output"
                    ]
                )
            ),
            role=role,
            timeout=Duration.minutes(5),
            memory_size=512,
            environment={
                "TELEGRAM_BOT_TOKEN": bot_token,
                "BEDROCK_MODEL_ID": os.getenv('BEDROCK_MODEL_ID', 'eu.anthropic.claude-3-5-sonnet-20240620-v1:0'),
                "BEDROCK_REGION": self.region,
                "S3_BUCKET_NAME": bucket.bucket_name,
                "DYNAMODB_TABLE_NAME": table.table_name
            },
            log_group=log_group,
            description="Telegram bot for receipt recognition"
        )
    
    def _create_api_gateway(self, lambda_func: _lambda.Function) -> apigateway.RestApi:
        """Create API Gateway for Telegram webhook"""
        api = apigateway.RestApi(
            self,
            "TelegramWebhookApi",
            rest_api_name="Receipt Bot Webhook",
            description="API Gateway for Telegram webhook",
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=apigateway.Cors.ALL_ORIGINS,
                allow_methods=["POST"],
                allow_headers=["Content-Type"]
            )
        )
        
        # Create webhook resource
        webhook_resource = api.root.add_resource("webhook")
        
        # Add POST method
        webhook_integration = apigateway.LambdaIntegration(lambda_func)
        
        webhook_resource.add_method(
            "POST",
            webhook_integration,
            method_responses=[
                apigateway.MethodResponse(
                    status_code="200",
                    response_parameters={
                        "method.response.header.Content-Type": True
                    }
                )
            ]
        )
        
        return api