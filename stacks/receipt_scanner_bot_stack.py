"""
Receipt Scanner Bot Stack - AWS CDK Infrastructure
"""

import os
import json
from typing import Any, Tuple

from aws_cdk.aws_lambda_python_alpha import PythonFunction
from aws_cdk.aws_lambda import IFunction
from aws_cdk import (
    Stack,
    Duration,
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
    CfnOutput,
    custom_resources as cr
)
from constructs import Construct
import aws_cdk.aws_rds as rds
import aws_cdk.aws_ec2 as ec2


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
        database, vpc, lambda_security_group = self._create_database_infrastructure()

        # Create resources
        receipt_bucket = self._create_s3_bucket()
        processing_queue, dlq = self._create_processing_queue()
        lambda_role = self._create_lambda_role(receipt_bucket, database, processing_queue)
        producer_lambda = self._create_producer_lambda(lambda_role, bot_token, processing_queue, main_log_group, vpc, lambda_security_group, database)
        consumer_lambda = self._create_consumer_lambda(lambda_role, processing_queue, receipt_bucket, main_log_group, vpc, lambda_security_group, database)
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

    def _create_lambda_role(self, bucket: s3.Bucket, database: rds.DatabaseInstance, queue: sqs.Queue) -> iam.Role:
        """Create IAM role for Lambda functions"""
        role = iam.Role(
            self, "ReceiptBotLambdaRole",
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

        role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[database.secret.secret_arn]
            )
        )

        bucket.grant_read_write(role)
        queue.grant_send_messages(role)
        queue.grant_consume_messages(role)

        return role

    def _create_producer_lambda(self, role: iam.Role, bot_token: str,
                           queue: sqs.Queue, log_group: logs.LogGroup,
                           vpc: ec2.Vpc, security_group: ec2.SecurityGroup,
                           database: rds.DatabaseInstance) -> _lambda.Function:
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
            vpc=vpc,
            security_groups=[security_group],
            environment={
                "TELEGRAM_BOT_TOKEN": bot_token,
                "SQS_QUEUE_URL": queue.queue_url,
                "DATABASE_SECRET_ARN": database.secret.secret_arn,
                "DOCUMENT_STORAGE_PROVIDER": "postgresql"
            },
            log_group=log_group,
            logging_format=_lambda.LoggingFormat.TEXT,
            description="Producer Lambda - Handles Telegram webhooks and queues messages"
        )

    def _create_consumer_lambda(self, role: iam.Role, queue: sqs.Queue,
                           bucket: s3.Bucket, log_group: logs.LogGroup,
                           vpc: ec2.Vpc, security_group: ec2.SecurityGroup,
                           database: rds.DatabaseInstance) -> _lambda.Function:
        """Create Consumer Lambda (processes SQS messages)"""

        consumer_lambda = PythonFunction(
            self, "ConsumerHandler",
            entry="lambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            index="consumer_handler.py",  # Consumer lambda file
            handler="lambda_handler",
            role=role,
            timeout=Duration.minutes(10),  # Longer timeout for processing
            memory_size=1024,  # More memory for OCR/LLM processing
            vpc=vpc,
            security_groups=[security_group],
            environment={
                "TELEGRAM_BOT_TOKEN": os.getenv('TELEGRAM_BOT_TOKEN'),
                "S3_BUCKET_NAME": bucket.bucket_name,
                "DATABASE_SECRET_ARN": database.secret.secret_arn,
                "DOCUMENT_STORAGE_PROVIDER": "postgresql",
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
                max_batching_window=Duration.seconds(5),
                max_concurrency=15,  # Control concurrent processing
                report_batch_item_failures=True  # Enable partial batch failure handling
            )
        )

        return consumer_lambda

    def _create_processing_queue(self) -> Tuple[sqs.Queue, sqs.Queue]:
        """Create SQS queue for async message processing"""

        # Dead Letter Queue for failed messages
        dlq = sqs.Queue(
            self, "ProcessingDeadLetterQueue",
            queue_name="receipt-bot-processing-dlq",
            retention_period=Duration.days(14),
            removal_policy=RemovalPolicy.DESTROY
        )

        # Main processing queue
        main_queue = sqs.Queue(
        self, "ProcessingQueue",
        queue_name="receipt-bot-processing",
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

    def _create_monitoring(self, queue: sqs.Queue, dlq: sqs.Queue,
                      producer_lambda: _lambda.Function,
                      consumer_lambda: _lambda.Function) -> None:
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

        CfnOutput(
            self, "DatabaseSecretArn",
            value=database.secret.secret_arn,
            description="Database credentials secret ARN"
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

    def _create_database_infrastructure(self) -> tuple[rds.DatabaseInstance, ec2.Vpc, ec2.SecurityGroup]:
        """Create RDS PostgreSQL instance and minimal VPC"""

        # Create VPC for RDS
        vpc = ec2.Vpc(
            self, "ReceiptBotVpc",
            max_azs=2,
            nat_gateways=0,  # No NAT needed - saves $45/month
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Database",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24
                )
            ]
        )

        # Security group for Lambda
        lambda_security_group = ec2.SecurityGroup(
            self, "ReceiptBotLambdaSecurityGroup",
            vpc=vpc,
            description="Security group for receipt bot lambdas"
        )

        # Security group for database
        db_security_group = ec2.SecurityGroup(
            self, "ReceiptBotDbSecurityGroup",
            vpc=vpc,
            description="Security group for receipt bot database"
        )

        # Allow Lambda to connect to database
        db_security_group.add_ingress_rule(
            peer=lambda_security_group,
            connection=ec2.Port.tcp(5432)
        )

        # Create database subnet group - FIXED VERSION
        db_subnet_group = rds.SubnetGroup(
            self, "DbSubnetGroup",
            description="Subnet group for database",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED)
        )

        # Create PostgreSQL instance
        database = rds.DatabaseInstance(
            self, "ReceiptBotDatabase",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_17
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T4G,
                ec2.InstanceSize.MICRO
            ),
            vpc=vpc,
            subnet_group=db_subnet_group,
            security_groups=[db_security_group],
            database_name="receipt_bot",
            credentials=rds.Credentials.from_generated_secret("postgres"),
            allocated_storage=20,
            backup_retention=Duration.days(7),
            deletion_protection=False,
            removal_policy=RemovalPolicy.DESTROY
        )

        return database, vpc, lambda_security_group

    def _create_database_schema(self, database: rds.DatabaseInstance, vpc: ec2.Vpc,
                            lambda_security_group: ec2.SecurityGroup) -> None:
        """Create database schema using custom resource"""

        # Create Lambda function for schema initialization from file
        schema_lambda = PythonFunction(
            self, "DatabaseSchemaHandler",
            entry="lambda",
            runtime=_lambda.Runtime.PYTHON_3_12,
            index="database_schema_handler.py",
            handler="lambda_handler",
            timeout=Duration.minutes(5),
            vpc=vpc,
            security_groups=[lambda_security_group],
            environment={
                "DATABASE_SECRET_ARN": database.secret.secret_arn
            }
        )

        # Grant permissions to read the secret
        database.secret.grant_read(schema_lambda)

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
                'SecretArn': database.secret.secret_arn,
                'DatabaseEndpoint': database.instance_endpoint.hostname
            }
        )

        # Ensure schema is created after database is ready
        schema_resource.node.add_dependency(database)
