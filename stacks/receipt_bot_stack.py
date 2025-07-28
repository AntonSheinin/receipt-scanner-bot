"""
    Receipt Bot Stack - AWS CDK Infrastructure
"""

import os
from typing import Any
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CustomResource,
    aws_lambda as _lambda,
    aws_apigateway as apigateway,
    aws_iam as iam,
    aws_logs as logs,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    CfnOutput,
    custom_resources as cr
)
from constructs import Construct
from dotenv import load_dotenv


load_dotenv()

class ReceiptBotStack(Stack):
    
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Get bot token
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN') or self.node.try_get_context("telegram_bot_token")
        
        if not bot_token:
            bot_token = "placeholder_token_for_bootstrap"
            print("⚠️  No bot token found. Set TELEGRAM_BOT_TOKEN in .env file")
        else:
            print("✅ Bot token loaded successfully")
        
        # Create resources
        receipt_bucket = self._create_s3_bucket()
        receipt_table = self._create_dynamodb_table()
        lambda_role = self._create_lambda_role(receipt_bucket, receipt_table)
        telegram_lambda = self._create_telegram_lambda(lambda_role, bot_token, receipt_bucket, receipt_table)
        api_gateway = self._create_api_gateway(telegram_lambda)
        
        # Setup webhook if bot token is valid
        if bot_token != "placeholder_token_for_bootstrap":
            webhook_url = f"{api_gateway.url}webhook"
            self._create_webhook_setup(bot_token, webhook_url, api_gateway)
        
        # Outputs
        self._create_outputs(api_gateway, receipt_bucket, receipt_table, bot_token)
    
    def _create_s3_bucket(self) -> s3.Bucket:
        """Create S3 bucket for receipt images"""
        return s3.Bucket(
            self, "ReceiptImagesBucket",
            bucket_name=f"receipt-images-{self.account}-{self.region}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            versioned=False,
            public_read_access=False,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="DeleteOldImages",
                    enabled=True,
                    expiration=Duration.days(90)
                )
            ]
        )
    
    def _create_dynamodb_table(self) -> dynamodb.Table:
        """Create DynamoDB table for receipt data"""
        table = dynamodb.Table(
            self, "ReceiptsTable",
            table_name="receipts",
            partition_key=dynamodb.Attribute(name="user_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="receipt_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=False
            )
        )
        
        # Add GSI for querying by date
        table.add_global_secondary_index(
            index_name="DateIndex",
            partition_key=dynamodb.Attribute(name="user_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="date", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL
        )
        
        # Add GSI for querying by store
        table.add_global_secondary_index(
            index_name="StoreIndex", 
            partition_key=dynamodb.Attribute(name="user_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="store_name", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL
        )
        
        return table
    
    def _create_lambda_role(self, bucket: s3.Bucket, table: dynamodb.Table) -> iam.Role:
        """Create IAM role for Lambda functions"""
        role = iam.Role(
            self, "TelegramLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
            ]
        )
        
        # Add permissions
        role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"]
            )
        )
        
        bucket.grant_read_write(role)
        table.grant_read_write_data(role)
        
        return role
    
    def _create_telegram_lambda(self, role: iam.Role, bot_token: str, bucket: s3.Bucket, table: dynamodb.Table) -> _lambda.Function:
        """Create main Telegram Lambda function"""
        
        log_group = logs.LogGroup(
            self, "TelegramHandlerLogGroup",
            log_group_name="/aws/lambda/TelegramHandler",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY
        )
        
        return _lambda.Function(
            self, "TelegramHandler",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="telegram_handler.lambda_handler",
            code=_lambda.Code.from_asset(
                "lambda",
                bundling=cdk.BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash", "-c",
                        "pip install -r requirements.txt -t /asset-output && "
                        "cp -r . /asset-output && "
                        "find /asset-output -name '__pycache__' -type d -exec rm -rf {} + || true"
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
            logging_format=_lambda.LoggingFormat.TEXT,
            description="Telegram bot for receipt recognition"
        )
    
    def _create_api_gateway(self, lambda_func: _lambda.Function) -> apigateway.RestApi:
        """Create API Gateway for Telegram webhook"""
        api = apigateway.RestApi(
            self, "TelegramWebhookApi",
            rest_api_name="Receipt Bot Webhook",
            description="API Gateway for Telegram webhook",
            deploy_options=apigateway.StageOptions(
                logging_level=apigateway.MethodLoggingLevel.INFO,
                data_trace_enabled=True,
                metrics_enabled=True
            )
        )
        
        # Create webhook resource and method
        webhook_resource = api.root.add_resource("webhook")
        webhook_resource.add_method(
            "POST",
            apigateway.LambdaIntegration(lambda_func, proxy=True),
            authorization_type=apigateway.AuthorizationType.NONE
        )
        
        # Grant API Gateway permission to invoke Lambda
        lambda_func.add_permission(
            "AllowAPIGatewayInvoke",
            principal=iam.ServicePrincipal("apigateway.amazonaws.com"),
            action="lambda:InvokeFunction",
            source_arn=f"{api.arn_for_execute_api()}/*/*"
        )
        
        return api
    
    def _create_webhook_setup(self, bot_token: str, webhook_url: str, api_gateway: apigateway.RestApi) -> None:
        """Create webhook setup custom resource"""
        
        # Create webhook setter Lambda
        webhook_setter = self._create_webhook_setter_lambda()
        
        # Create custom resource provider
        webhook_provider = cr.Provider(
            self, "WebhookSetterProvider",
            on_event_handler=webhook_setter,
            log_retention=logs.RetentionDays.ONE_WEEK
        )
        
        # Create custom resource
        webhook_setup = CustomResource(
            self, "WebhookSetterResource",
            service_token=webhook_provider.service_token,
            properties={
                'WebhookUrl': webhook_url,
                'BotToken': bot_token,
                'Version': '1.0'
            }
        )
        
        # Ensure proper order
        webhook_setup.node.add_dependency(api_gateway)
    
    def _create_webhook_setter_lambda(self) -> _lambda.Function:
        """Create Lambda function for webhook setup"""
        
        log_group = logs.LogGroup(
            self, "WebhookSetterLogGroup",
            log_group_name="/aws/lambda/WebhookSetter",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY
        )
        
        return _lambda.Function(
            self, "WebhookSetterHandler",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="webhook_setter_handler.lambda_handler",
            code=_lambda.Code.from_asset(
                "lambda",
                bundling=cdk.BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash", "-c",
                        "pip install urllib3 -t /asset-output && "
                        "cp -r . /asset-output && "
                        "find /asset-output -name '__pycache__' -type d -exec rm -rf {} + || true"
                    ]
                )
            ),
            timeout=Duration.minutes(2),
            memory_size=256,
            log_group=log_group,
            logging_format=_lambda.LoggingFormat.TEXT,
            description="Telegram webhook setter"
        )
    
    def _create_outputs(self, api_gateway: apigateway.RestApi, bucket: s3.Bucket, table: dynamodb.Table, bot_token: str) -> None:
        """Create stack outputs"""
        
        CfnOutput(
            self, "TelegramWebhookUrl",
            value=f"{api_gateway.url}webhook",
            description="Telegram webhook URL"
        )
        
        CfnOutput(
            self, "ReceiptsBucketName",
            value=bucket.bucket_name,
            description="S3 bucket for receipt images"
        )
        
        CfnOutput(
            self, "ReceiptsTableName",
            value=table.table_name,
            description="DynamoDB table for receipt data"
        )
        
        if bot_token != "placeholder_token_for_bootstrap":
            CfnOutput(
                self, "WebhookSetupStatus",
                value="Webhook configured automatically",
                description="Webhook setup status"
            )
        else:
            CfnOutput(
                self, "WebhookSetupStatus",
                value="Set TELEGRAM_BOT_TOKEN and redeploy",
                description="Webhook setup status"
            )