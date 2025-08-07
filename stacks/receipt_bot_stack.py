"""
Receipt Bot Stack - AWS CDK Infrastructure
"""

import os
import json
from typing import Any

from aws_cdk.aws_lambda_python_alpha import PythonFunction
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CustomResource,
    aws_lambda as _lambda,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as integrations,
    aws_iam as iam,
    aws_logs as logs,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    CfnOutput,
    custom_resources as cr
)
from constructs import Construct


class ReceiptBotStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Get bot token
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')

        if not bot_token:
            bot_token = "placeholder_token_for_bootstrap"
            print("⚠️ No bot token found. Set TELEGRAM_BOT_TOKEN in .env file")
        else:
            print("✅ Bot token loaded successfully")

        # Create single log group for all components
        main_log_group = self._create_main_log_group()

        # Create resources
        receipt_bucket = self._create_s3_bucket()
        receipt_table = self._create_dynamodb_table()
        lambda_role = self._create_lambda_role(receipt_bucket, receipt_table)
        telegram_lambda = self._create_telegram_lambda(lambda_role, bot_token, receipt_bucket, receipt_table, main_log_group)
        api_gateway = self._create_api_gateway(telegram_lambda, main_log_group)

        # Setup webhook if bot token is valid
        if bot_token != "placeholder_token_for_bootstrap":
            webhook_url = f"{api_gateway.api_endpoint}/webhook"
            self._create_webhook_setup(bot_token, webhook_url, api_gateway, main_log_group)

        # Outputs
        self._create_outputs(api_gateway, receipt_bucket, receipt_table, bot_token, main_log_group)

    def _create_main_log_group(self) -> logs.LogGroup:
        """Create single log group for all components"""
        return logs.LogGroup(
            self, "ReceiptBotLogGroup",
            log_group_name="/aws/receipt-bot/all-logs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY
        )

    def _create_s3_bucket(self) -> s3.Bucket:
        """Create S3 bucket for receipt images"""
        return s3.Bucket(
            self, "ReceiptImagesBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True
        )

    def _create_dynamodb_table(self) -> dynamodb.Table:
        """Create DynamoDB table for receipt data"""
        table = dynamodb.Table(
            self, "ReceiptsTable",
            partition_key=dynamodb.Attribute(name="user_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="receipt_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY
        )

        # Add GSI for querying by date
        table.add_global_secondary_index(
            index_name="DateIndex",
            partition_key=dynamodb.Attribute(name="user_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="date", type=dynamodb.AttributeType.STRING)
        )

        # Add GSI for querying by store
        table.add_global_secondary_index(
            index_name="StoreIndex",
            partition_key=dynamodb.Attribute(name="user_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="store_name", type=dynamodb.AttributeType.STRING)
        )

        table.add_global_secondary_index(
            index_name="PaymentMethodIndex",
            partition_key=dynamodb.Attribute(name="user_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="payment_method", type=dynamodb.AttributeType.STRING)
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
                actions=["bedrock:InvokeModel"],
                resources=["*"]
            )
        )

        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "textract:DetectDocumentText",
                    "textract:AnalyzeExpense"
                ],
                resources=["*"]
            )
        )

        bucket.grant_read_write(role)
        table.grant_read_write_data(role)

        return role

    def _create_telegram_lambda(self, role: iam.Role, bot_token: str, bucket: s3.Bucket, table: dynamodb.Table, log_group: logs.LogGroup) -> _lambda.Function:
        """Create main Telegram Lambda function"""
        return PythonFunction(
            self, "TelegramHandler",
            entry="lambda",  # Folder that contains telegram_bot_handler.py and requirements.txt
            runtime=_lambda.Runtime.PYTHON_3_12,
            index="telegram_bot_handler.py",  # filename
            handler="lambda_handler",     # function name inside the file
            role=role,
            timeout=Duration.minutes(5),
            memory_size=1024,
            environment={
                "TELEGRAM_BOT_TOKEN": bot_token,
                "S3_BUCKET_NAME": bucket.bucket_name,
                "DYNAMODB_TABLE_NAME": table.table_name,
                "BEDROCK_REGION": os.getenv('BEDROCK_REGION'),
                "BEDROCK_MODEL_ID": os.getenv('BEDROCK_MODEL_ID'),
                "OCR_PROVIDER": os.getenv('OCR_PROVIDER'),
                "LLM_PROVIDER": os.getenv('LLM_PROVIDER'),
                "DOCUMENT_PROCESSING_MODE": os.getenv('DOCUMENT_PROCESSING_MODE'),
                "OCR_PROCESSING_MODE": os.getenv('OCR_PROCESSING_MODE'),
                "GOOGLE_CREDENTIALS_JSON": os.getenv('GOOGLE_CREDENTIALS_JSON'),
                "OPENAI_API_KEY": os.getenv('OPENAI_API_KEY'),
                "OPENAI_MODEL_ID": os.getenv('OPENAI_MODEL_ID')
            },
            log_group=log_group,
            logging_format=_lambda.LoggingFormat.TEXT
        )

    def _create_api_gateway(self, lambda_func: _lambda.Function, log_group: logs.LogGroup) -> apigwv2.HttpApi:
        """Create HTTP API for Telegram webhook with custom access logs"""

        lambda_integration = integrations.HttpLambdaIntegration(
            "TelegramWebhookIntegration",
            handler=lambda_func,
            timeout=Duration.seconds(29)
        )

        # Create the HTTP API
        api = apigwv2.HttpApi(
            self, "TelegramWebhookHttpApi",
            api_name="Receipt Bot Webhook",
            description="Telegram webhook endpoint for receipt bot"
        )

        # Add webhook route
        api.add_routes(
            path="/webhook",
            methods=[apigwv2.HttpMethod.POST],
            integration=lambda_integration
        )

        # Get the default stage L1 resource
        default_stage = api.default_stage.node.default_child

        # Override access log settings on the existing stage
        default_stage.add_property_override("AccessLogSettings.DestinationArn", log_group.log_group_arn)
        default_stage.add_property_override(
            "AccessLogSettings.Format",
            json.dumps({
                "requestId": "$context.requestId",
                "status": "$context.status",
                "path": "$context.path",
                "integrationErrorMessage": "$context.integration.error"
            })
        )

        # Ensure the log group can be written to by API Gateway
        log_group.grant_write(iam.ServicePrincipal("apigateway.amazonaws.com"))

        return api

    def _create_webhook_setup(self, bot_token: str, webhook_url: str, api_gateway: apigwv2.HttpApi, log_group: logs.LogGroup) -> None:
        """Create webhook setup custom resource"""

        # Create webhook setter Lambda
        webhook_setter = self._create_webhook_setter_lambda(log_group)

        # Create custom resource provider
        webhook_provider = cr.Provider(
            self, "WebhookSetterProvider",
            on_event_handler=webhook_setter
        )

        # Create custom resource
        webhook_setup = CustomResource(
            self, "WebhookSetterResource",
            service_token=webhook_provider.service_token,
            properties={
                'WebhookUrl': webhook_url,
                'BotToken': bot_token
            }
        )

        webhook_setup.node.add_dependency(api_gateway)

    def _create_webhook_setter_lambda(self, log_group: logs.LogGroup) -> _lambda.Function:
        """Create Lambda function for webhook setup"""
        return PythonFunction(
            self, "WebhookSetterHandler",
            entry="lambda",  # Folder that contains webhook_setter_handler.py and requirements.txt
            index="webhook_setter_handler.py",  # File with the Lambda handler
            handler="lambda_handler",           # Function inside the file
            runtime=_lambda.Runtime.PYTHON_3_12,
            timeout=Duration.minutes(2),
            environment={
                "TELEGRAM_BOT_TOKEN": os.getenv('TELEGRAM_BOT_TOKEN'),
                "BEDROCK_REGION": os.getenv('BEDROCK_REGION'),
                "BEDROCK_MODEL_ID": os.getenv('BEDROCK_MODEL_ID'),
                "OCR_PROVIDER": os.getenv('OCR_PROVIDER'),
                "LLM_PROVIDER": os.getenv('LLM_PROVIDER'),
                "DOCUMENT_PROCESSING_MODE": os.getenv('DOCUMENT_PROCESSING_MODE'),
                "OCR_PROCESSING_MODE": os.getenv('OCR_PROCESSING_MODE'),
                "GOOGLE_CREDENTIALS_JSON": os.getenv('GOOGLE_CREDENTIALS_JSON'),
                "OPENAI_API_KEY": os.getenv('OPENAI_API_KEY'),
                "OPENAI_MODEL_ID": os.getenv('OPENAI_MODEL_ID')
            },
            log_group=log_group,
            logging_format=_lambda.LoggingFormat.TEXT
        )

    def _create_outputs(self, api_gateway: apigwv2.HttpApi, bucket: s3.Bucket, table: dynamodb.Table, bot_token: str, log_group: logs.LogGroup) -> None:
        """Create stack outputs"""

        CfnOutput(
            self, "TelegramWebhookUrl",
            value=f"{api_gateway.api_endpoint}/webhook"
        )

        CfnOutput(
            self, "ReceiptsBucketName",
            value=bucket.bucket_name
        )

        CfnOutput(
            self, "ReceiptsTableName",
            value=table.table_name
        )

        CfnOutput(
            self, "LogGroupName",
            value=log_group.log_group_name,
            description="CloudWatch log group for all components"
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

