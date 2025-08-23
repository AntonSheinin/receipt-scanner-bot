"""
    Receipt Scanner Bot Stack - AWS CDK Infrastructure
"""

import os
import json
from typing import Any, Tuple

import aws_cdk.aws_rds as rds
import aws_cdk.aws_ec2 as ec2
from aws_cdk.aws_lambda import IFunction
from aws_cdk.aws_lambda_python_alpha import PythonFunction, BundlingOptions
import aws_cdk.aws_lambda_python_alpha as _lambda_python

from constructs import Construct
from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    SecretValue,
    RemovalPolicy,
    CustomResource,
    aws_lambda as _lambda,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as integrations,
    aws_lambda_event_sources as lambda_event_sources,
    aws_iam as iam,
    aws_logs as logs,
    aws_s3 as s3,
    aws_sqs as sqs,
    aws_cloudwatch as cloudwatch,
    custom_resources as cr,
)


class ReceiptScannerBotStack(Stack):

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

        # Create database infrastructure
        database = self._create_database_infrastructure()
        self._create_database_schema(database, main_log_group)

        # Create resources
        receipt_bucket = self._create_s3_bucket()
        processing_queue, dlq = self._create_processing_queue()

        producer_role = self._create_producer_lambda_role(processing_queue)
        consumer_role = self._create_consumer_lambda_role(receipt_bucket, database, processing_queue)

        producer_lambda = self._create_producer_lambda(producer_role, bot_token, processing_queue, main_log_group)
        consumer_lambda = self._create_consumer_lambda(consumer_role, processing_queue, receipt_bucket, main_log_group, database)

        api_gateway = self._create_api_gateway(producer_lambda, main_log_group)

        # Setup webhook if bot token is valid
        if bot_token != "placeholder_token_for_bootstrap":
            webhook_url = f"{api_gateway.api_endpoint}/webhook"
            self._create_webhook_setup(bot_token, webhook_url, api_gateway, main_log_group)

        self._create_monitoring(processing_queue, dlq, producer_lambda, consumer_lambda)

        # Outputs
        self._create_outputs(
            api_gateway, receipt_bucket, database, processing_queue,
            bot_token, main_log_group, producer_lambda, consumer_lambda
        )

    def _create_main_log_group(self) -> logs.LogGroup:
        """Create single log group for all components"""
        return logs.LogGroup(
            self, "ReceiptScannerBotLogGroup",
            log_group_name="/aws/receipt-scanner-bot/all-logs",
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

    def _create_producer_lambda_role(self, queue: sqs.Queue) -> iam.Role:
        """Create IAM role for Producer Lambda"""
        role = iam.Role(
            self, "ReceiptBotProducerLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
            ]
        )

        # Only SQS permissions for producer
        queue.grant_send_messages(role)

        return role

    def _create_consumer_lambda_role(self, bucket: s3.Bucket, database: rds.DatabaseInstance, queue: sqs.Queue) -> iam.Role:
        """Create IAM role for Consumer Lambda"""
        role = iam.Role(
            self, "ReceiptBotConsumerLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
            ]
        )

        # Consumer needs all permissions
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
        queue.grant_consume_messages(role)

        return role

    def _create_producer_lambda(self, role: iam.Role, bot_token: str, queue: sqs.Queue, log_group: logs.LogGroup,) -> _lambda.Function:
        """Create Producer Lambda (webhook handler - queues messages only)"""

        return PythonFunction(
            self, "ProducerHandler",
            entry="lambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            index="telegram_bot_handler.py",  # Producer lambda file
            handler="lambda_handler",
            role=role,
            timeout=Duration.seconds(30),  # Short timeout for fast webhook response
            memory_size=256,  # Minimal memory for webhook handling
            environment={
                "TELEGRAM_BOT_TOKEN": bot_token,
                "SQS_QUEUE_URL": queue.queue_url
            },
            log_group=log_group,
            logging_format=_lambda.LoggingFormat.TEXT,
            description="Producer Lambda - Handles Telegram webhooks and queues messages"
        )

    def _create_consumer_lambda(
        self,
        role: iam.Role,
        queue: sqs.Queue,
        bucket: s3.Bucket,
        log_group: logs.LogGroup,
        database: rds.DatabaseInstance
        ) -> _lambda.Function:
        """Create Consumer Lambda (processes SQS messages)"""

        consumer_lambda = PythonFunction(
            self, "ConsumerHandler",
            entry="lambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            index="consumer_handler.py",
            handler="lambda_handler",
            role=role,
            timeout=Duration.minutes(10),  # Longer timeout for processing
            memory_size=1024,  # More memory for OCR/LLM processing
            bundling=_lambda_python.BundlingOptions(
            # Critical: exclude large files and cache directories
                asset_excludes=[
                    "**/__pycache__/**",
                    "**/*.pyc",
                    "**/.git/**",
                    "**/tests/**",
                    "**/docs/**",
                    "**/*.md",
                    "requirements-dev.txt",
                    ".env*",
                    ".venv/**"
                ]
            ),
            environment={
                "DB_USER": os.getenv('DB_USER'),
                "DB_PASSWORD": os.getenv('DB_PASSWORD'),
                "DB_NAME": os.getenv('DB_NAME'),
                "DB_PORT": os.getenv('DB_PORT'),
                "DB_HOST": database.instance_endpoint.hostname,
                "TELEGRAM_BOT_TOKEN": os.getenv('TELEGRAM_BOT_TOKEN'),
                "S3_BUCKET_NAME": bucket.bucket_name,
                "DOCUMENT_STORAGE_PROVIDER": os.getenv('DOCUMENT_STORAGE_PROVIDER'),
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
            logging_format=_lambda.LoggingFormat.TEXT,
            retry_attempts=0,  # SQS handles retries
            description="Consumer Lambda - Processes SQS messages via OrchestrationService"
        )

        # Add SQS event source to trigger consumer
        consumer_lambda.add_event_source(
            lambda_event_sources.SqsEventSource(
                queue,
                batch_size=1,  # Process one message at a time for better error handling
                max_concurrency=15,  # Control concurrent processing
                # report_batch_item_failures=True  # Enable partial batch failure handling - only need for batch_size > 1
            )
        )

        return consumer_lambda

    def _create_processing_queue(self) -> Tuple[sqs.Queue, sqs.Queue]:
        """Create SQS queue for async message processing"""

        # Dead Letter Queue for failed messages
        dlq = sqs.Queue(
            self, "ProcessingDeadLetterQueue",
            queue_name="receipt-bot-processing-dlq.fifo",
            fifo=True,
            content_based_deduplication=True,
            retention_period=Duration.days(7),
            removal_policy=RemovalPolicy.DESTROY
        )

        # Main processing queue
        main_queue = sqs.Queue(
        self, "ProcessingQueue",
        queue_name="receipt-bot-processing.fifo",
        fifo=True,
        content_based_deduplication=False,
        visibility_timeout=Duration.minutes(15),
        retention_period=Duration.days(4),
        receive_message_wait_time=Duration.seconds(20),
        dead_letter_queue=sqs.DeadLetterQueue(
            max_receive_count=3,
            queue=dlq
        ),
        removal_policy=RemovalPolicy.DESTROY
        )

        return main_queue, dlq

    def _create_monitoring(
            self, queue: sqs.Queue,
            dlq: sqs.Queue,
            producer_lambda: _lambda.Function,
            consumer_lambda: _lambda.Function
        ) -> None:
        """Create CloudWatch monitoring and alarms"""

        # Queue depth alarm
        cloudwatch.Alarm(
            self, "QueueDepthAlarm",
            alarm_name="receipt-bot-queue-depth",
            metric=queue.metric("ApproximateNumberOfVisibleMessages",
                period=Duration.minutes(5),
                statistic="Average"
            ),
            threshold=50,
            evaluation_periods=2,
            alarm_description="High queue depth - messages are backing up"
        )

        # Producer Lambda error rate alarm
        cloudwatch.Alarm(
            self, "ProducerErrorRateAlarm",
            alarm_name="receipt-bot-producer-errors",
            metric=producer_lambda.metric_errors(
                period=Duration.minutes(5)
            ),
            threshold=5,
            evaluation_periods=2,
            alarm_description="High error rate in producer Lambda"
        )

        # Consumer Lambda error rate alarm
        cloudwatch.Alarm(
            self, "ConsumerErrorRateAlarm",
            alarm_name="receipt-bot-consumer-errors",
            metric=consumer_lambda.metric_errors(
                period=Duration.minutes(5)
            ),
            threshold=3,
            evaluation_periods=2,
            alarm_description="High error rate in consumer Lambda"
        )

        # Consumer Lambda duration alarm
        cloudwatch.Alarm(
            self, "ConsumerDurationAlarm",
            alarm_name="receipt-bot-consumer-duration",
            metric=consumer_lambda.metric_duration(
                period=Duration.minutes(5)
            ),
            threshold=Duration.minutes(8).to_milliseconds(),
            evaluation_periods=2,
            alarm_description="Consumer Lambda taking too long to process messages"
        )

        cloudwatch.Alarm(
            self, "DeadLetterQueueAlarm",
            alarm_name="receipt-bot-dlq-messages",
            metric=dlq.metric("ApproximateNumberOfVisibleMessages",
                period=Duration.minutes(5),
                statistic="Average"
            ),
            threshold=1,
            evaluation_periods=1,
            alarm_description="Messages in dead letter queue - manual intervention needed"
        )

    def _create_api_gateway(self, lambda_func: IFunction, log_group: logs.LogGroup) -> apigwv2.HttpApi:
        """Create HTTP API for Telegram webhook with custom access logs"""

        lambda_integration = integrations.HttpLambdaIntegration(
            "TelegramWebhookIntegration",
            handler=lambda_func,
            timeout=Duration.seconds(29)
        )

        # Create the HTTP API
        api = apigwv2.HttpApi(
            self, "TelegramWebhookHttpApi",
            api_name="Receipt Scanner Bot Webhook",
            description="Telegram webhook endpoint for receipt scanner bot"
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

        # Create custom resource provider
        webhook_provider = cr.Provider(
            self, "WebhookSetterProvider",
            on_event_handler=self._create_webhook_setter_lambda(log_group)
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
            entry="lambda",
            index="webhook_setter_handler.py",
            handler="lambda_handler",
            runtime=_lambda.Runtime.PYTHON_3_12,
            bundling=_lambda_python.BundlingOptions(
            # Critical: exclude large files and cache directories
                asset_excludes=[
                    "**/__pycache__/**",
                    "**/*.pyc",
                    "**/.git/**",
                    "**/tests/**",
                    "**/docs/**",
                    "**/*.md",
                    "requirements-dev.txt",
                    ".env*",
                    ".venv/**"
                ]
            ),
            timeout=Duration.minutes(2),
            environment={
                "TELEGRAM_BOT_TOKEN": os.getenv('TELEGRAM_BOT_TOKEN', ''),
                "BEDROCK_REGION": os.getenv('BEDROCK_REGION', ''),
                "BEDROCK_MODEL_ID": os.getenv('BEDROCK_MODEL_ID', ''),
                "OCR_PROVIDER": os.getenv('OCR_PROVIDER', ''),
                "LLM_PROVIDER": os.getenv('LLM_PROVIDER', ''),
                "DOCUMENT_PROCESSING_MODE": os.getenv('DOCUMENT_PROCESSING_MODE', ''),
                "OCR_PROCESSING_MODE": os.getenv('OCR_PROCESSING_MODE', ''),
                "GOOGLE_CREDENTIALS_JSON": os.getenv('GOOGLE_CREDENTIALS_JSON', ''),
                "OPENAI_API_KEY": os.getenv('OPENAI_API_KEY', ''),
                "OPENAI_MODEL_ID": os.getenv('OPENAI_MODEL_ID', '')
            },
            log_group=log_group,
            logging_format=_lambda.LoggingFormat.TEXT
        )

    def _create_outputs(self, api_gateway: apigwv2.HttpApi, bucket: s3.Bucket,
                    database: rds.DatabaseInstance, queue: sqs.Queue, bot_token: str,
                    log_group: logs.LogGroup, producer_lambda: _lambda.Function,
                    consumer_lambda: _lambda.Function) -> None:
        """Create stack outputs"""

        CfnOutput(
            self, "TelegramWebhookUrl",
            value=f"{api_gateway.api_endpoint}/webhook",
            description="Telegram webhook URL"
        )

        CfnOutput(
            self, "ReceiptsBucketName",
            value=bucket.bucket_name,
            description="S3 bucket for receipt images"
        )

        CfnOutput(
            self, "ProcessingQueueUrl",
            value=queue.queue_url,
            description="SQS queue for async message processing"
        )

        CfnOutput(
            self, "ProcessingQueueName",
            value=queue.queue_name,
            description="SQS queue name"
        )

        CfnOutput(
            self, "LogGroupName",
            value=log_group.log_group_name,
            description="CloudWatch log group for all components"
        )

        CfnOutput(
            self, "ProducerLambdaName",
            value=producer_lambda.function_name,
            description="Producer Lambda function name (webhook handler)"
        )

        CfnOutput(
            self, "ConsumerLambdaName",
            value=consumer_lambda.function_name,
            description="Consumer Lambda function name (SQS processor)"
        )

        CfnOutput(
        self, "DatabaseEndpoint",
        value=database.instance_endpoint.hostname,
        description="RDS PostgreSQL endpoint"
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

    def _create_database_infrastructure(self) -> rds.DatabaseInstance:
        """Create publicly accessible RDS PostgreSQL instance with defaults"""

        default_vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)

        # Create security group that allows PostgreSQL access
        db_security_group = ec2.SecurityGroup(
            self, "ReceiptBotDbSecurityGroup",
            vpc=default_vpc,
            description="Security group for publicly accessible database",
            allow_all_outbound=False
        )

        db_security_group.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),  # Allow from anywhere
            connection=ec2.Port.tcp(5432),
            description="PostgreSQL access from internet"
        )

        return rds.DatabaseInstance(
            self, "ReceiptBotDatabase",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_17
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T4G,
                ec2.InstanceSize.MICRO
            ),
            vpc=default_vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_groups=[db_security_group],
            database_name=os.getenv('DB_NAME'),
            credentials=rds.Credentials.from_username(
                username=os.getenv('DB_USER'),
                password=SecretValue.unsafe_plain_text(os.getenv('DB_PASSWORD'))
            ),
            allocated_storage=20,
            backup_retention=Duration.days(7),
            deletion_protection=False,
            removal_policy=RemovalPolicy.DESTROY,
            publicly_accessible=True
        )

    def _create_database_schema(self, database: rds.DatabaseInstance, log_group: logs.LogGroup) -> None:
        """Create database schema using custom resource"""

        # Create Lambda function for schema initialization from file
        schema_lambda = PythonFunction(
            self, "DatabaseSchemaHandler",
            entry="lambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            index="database_schema_handler.py",
            handler="lambda_handler",
            timeout=Duration.minutes(2),
            environment={
                "DB_HOST": database.instance_endpoint.hostname,
                "DB_PORT": os.getenv('DB_PORT'),
                "DB_NAME": os.getenv('DB_NAME'),
                "DB_USER": os.getenv('DB_USER'),
                "DB_PASSWORD": os.getenv('DB_PASSWORD')
            },
            memory_size=256,
            retry_attempts=0,
            log_group=log_group,
            logging_format=_lambda.LoggingFormat.TEXT,
        )

        # Create custom resource provider
        schema_provider = cr.Provider(
            self, "DatabaseSchemaProvider",
            on_event_handler=schema_lambda
        )

        # Create the custom resource
        schema_resource = CustomResource(
            self, "DatabaseSchemaResource",
            service_token=schema_provider.service_token,
            properties={
                'DatabaseEndpoint': database.instance_endpoint.hostname
            }
        )

        # Ensure schema is created after database is ready
        schema_resource.node.add_dependency(database)
