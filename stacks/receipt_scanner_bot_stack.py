"""
    Receipt Scanner Bot Stack - AWS CDK Infrastructure
"""

import json
from typing import Any, Tuple

from aws_cdk import Tags
import aws_cdk.aws_rds as rds
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_ecr_assets as ecr_assets
from aws_cdk.aws_lambda import IFunction

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
    aws_secretsmanager as secretsmanager
)


class ReceiptScannerBotStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, stage: str = "dev", **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Store stage for use throughout the stack
        self.stage = stage
        self.is_production = stage == "prod"

        app_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "AppSecret",
            secret_name=f"receipt-scanner-bot-{self.stage}"
        )

        bot_token = app_secret.secret_value_from_json("TELEGRAM_BOT_TOKEN").unsafe_unwrap()

        print(f"🏗️  Building {construct_id} for stage: {stage}")

        # Create single log group for all components
        main_log_group = self._create_main_log_group()

        self.lambda_image = self._create_lambda_image()

        # Create database infrastructure
        database = self._create_database_infrastructure(app_secret)
        self._create_database_setup(database, main_log_group)

        # Create resources
        receipt_bucket = self._create_s3_bucket()
        processing_queue, dlq = self._create_processing_queue()

        producer_role = self._create_producer_lambda_role(processing_queue, app_secret)
        consumer_role = self._create_consumer_lambda_role(receipt_bucket, database, processing_queue, app_secret)

        producer_lambda = self._create_producer_lambda(producer_role, bot_token, processing_queue, main_log_group)
        consumer_lambda = self._create_consumer_lambda(consumer_role, processing_queue, receipt_bucket, main_log_group, database)

        api_gateway = self._create_api_gateway(producer_lambda, main_log_group)

        # Setup webhook if bot token is valid
        if bot_token:
            webhook_url = f"{api_gateway.api_endpoint}/webhook"
            self._create_webhook_setup(bot_token, webhook_url, api_gateway, main_log_group, app_secret)

        self._create_monitoring(processing_queue, dlq, producer_lambda, consumer_lambda)

        # Outputs
        self._create_outputs(
            api_gateway, receipt_bucket, database, processing_queue,
            bot_token, main_log_group, producer_lambda, consumer_lambda
        )

    def _create_lambda_image(self) -> ecr_assets.DockerImageAsset:
        """Create single shared Docker image for all Lambda functions"""
        docker_image = ecr_assets.DockerImageAsset(
            self, "ReceiptScannerLambdaImage",
            directory="lambda",
            asset_name=f"receipt-scanner-lambda-{self.stage}"
        )

        # Add resource-specific tags
        Tags.of(docker_image).add("ResourceType", "DockerImage")
        Tags.of(docker_image).add("Component", "LambdaRuntime")

        return docker_image

    def _create_main_log_group(self) -> logs.LogGroup:
        """Create single log group for all components"""
        log_group = logs.LogGroup(
            self, "ReceiptScannerBotLogGroup",
            log_group_name=f"/aws/receipt-scanner-bot/{self.stage}/all-logs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY
        )

        # Add resource-specific tags
        Tags.of(log_group).add("ResourceType", "LogGroup")
        Tags.of(log_group).add("Component", "Logging")

        return log_group

    def _create_s3_bucket(self) -> s3.Bucket:
        """Create S3 bucket for receipt images"""
        bucket = s3.Bucket(
            self, "ReceiptImagesBucket",
            bucket_name=f"receipt-scanner-{self.stage}-{self.account}-{self.region}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True if self.stage == "dev" else False
        )

        # Add resource-specific tags
        Tags.of(bucket).add("ResourceType", "S3Bucket")
        Tags.of(bucket).add("Component", "Storage")
        Tags.of(bucket).add("DataType", "ReceiptImages")

        return bucket

    def _create_producer_lambda_role(self, queue: sqs.Queue, secret: secretsmanager.Secret) -> iam.Role:
        """Create IAM role for Producer Lambda"""
        role = iam.Role(
            self, "ReceiptBotProducerLambdaRole",
            role_name=f"receipt-bot-{self.stage}-producer-lambda-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
            ]
        )

        # Only SQS permissions for producer
        queue.grant_send_messages(role)

        secret.grant_read(role)

        # Add resource-specific tags
        Tags.of(role).add("ResourceType", "IAMRole")
        Tags.of(role).add("Component", "ProducerLambda")

        return role

    def _create_consumer_lambda_role(self, bucket: s3.Bucket, database: rds.DatabaseInstance, queue: sqs.Queue, secret: secretsmanager.Secret) -> iam.Role:
        """Create IAM role for Consumer Lambda"""
        role = iam.Role(
            self, "ReceiptBotConsumerLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            role_name=f"receipt-bot-{self.stage}-consumer-lambda-role",
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

        secret.grant_read(role)

        # Add resource-specific tags
        Tags.of(role).add("ResourceType", "IAMRole")
        Tags.of(role).add("Component", "ConsumerLambda")

        return role

    def _create_producer_lambda(self, role: iam.Role, bot_token: str, queue: sqs.Queue, log_group: logs.LogGroup,) -> _lambda.Function:
        """Create Producer Lambda (webhook handler - queues messages only)"""

        producer_lambda = _lambda.Function(
            self, "ProducerHandler",
            function_name=f"receipt-bot-{self.stage}-producer",
            code=_lambda.Code.from_ecr_image(
                repository=self.lambda_image.repository,
                tag_or_digest=self.lambda_image.asset_hash,
                cmd=["telegram_bot_handler.lambda_handler"]
            ),
            handler=_lambda.Handler.FROM_IMAGE,
            runtime=_lambda.Runtime.FROM_IMAGE,
            role=role,
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "SQS_QUEUE_URL": queue.queue_url,
                "STAGE": self.stage
            },
            log_group=log_group,
            description=f"Producer Lambda - Handles Telegram webhooks ({self.stage})"
        )

        # Add resource-specific tags
        Tags.of(producer_lambda).add("ResourceType", "LambdaFunction")
        Tags.of(producer_lambda).add("Component", "Producer")
        Tags.of(producer_lambda).add("Handler", "WebhookHandler")

        return producer_lambda

    def _create_consumer_lambda(self, role: iam.Role, queue: sqs.Queue, bucket: s3.Bucket,
                               log_group: logs.LogGroup, database: rds.DatabaseInstance) -> _lambda.Function:
        """Create Consumer Lambda using shared container image"""
        consumer_lambda = _lambda.Function(
            self, "ConsumerHandler",
            function_name=f"receipt-bot-{self.stage}-consumer",
            code=_lambda.Code.from_ecr_image(
                repository=self.lambda_image.repository,
                tag_or_digest=self.lambda_image.asset_hash,
                cmd=["consumer_handler.lambda_handler"]
            ),
            handler=_lambda.Handler.FROM_IMAGE,
            runtime=_lambda.Runtime.FROM_IMAGE,
            role=role,
            timeout=Duration.minutes(10),
            memory_size=1536,
            environment={
                "DB_HOST": database.instance_endpoint.hostname,
                "S3_BUCKET_NAME": bucket.bucket_name,
                "STAGE": self.stage
            },
            log_group=log_group,
            description=f"Consumer Lambda - Processes SQS messages ({self.stage})"
        )

        consumer_lambda.add_event_source(
            lambda_event_sources.SqsEventSource(
                queue,
                batch_size=5, # for processing multiple messages of one album at once
                max_concurrency=15
            )
        )

        # Add resource-specific tags
        Tags.of(consumer_lambda).add("ResourceType", "LambdaFunction")
        Tags.of(consumer_lambda).add("Component", "Consumer")
        Tags.of(consumer_lambda).add("Handler", "SQSProcessor")

        return consumer_lambda

    def _create_processing_queue(self) -> Tuple[sqs.Queue, sqs.Queue]:
        """Create SQS queue for async message processing"""

        # Dead Letter Queue for failed messages
        dlq = sqs.Queue(
            self, "ProcessingDeadLetterQueue",
            queue_name=f"receipt-bot-{self.stage}-processing-dlq.fifo",
            fifo=True,
            content_based_deduplication=True,
            retention_period=Duration.days(7),
            removal_policy=RemovalPolicy.DESTROY
        )

        Tags.of(dlq).add("ResourceType", "SQSQueue")
        Tags.of(dlq).add("Component", "DeadLetterQueue")

        # Main processing queue
        main_queue = sqs.Queue(
            self, "ProcessingQueue",
            queue_name=f"receipt-bot-{self.stage}-processing.fifo",
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

        Tags.of(main_queue).add("ResourceType", "SQSQueue")
        Tags.of(main_queue).add("Component", "ProcessingQueue")

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
            alarm_name=f"receipt-bot-{self.stage}-queue-depth",
            metric=queue.metric("ApproximateNumberOfVisibleMessages",
                period=Duration.minutes(5),
                statistic="Average"
            ),
            threshold=50,
            evaluation_periods=2,
            alarm_description=f"High queue depth in {self.stage} - messages are backing up"
        )

        # Producer Lambda error rate alarm
        cloudwatch.Alarm(
            self, "ProducerErrorRateAlarm",
            alarm_name=f"receipt-bot-{self.stage}-producer-errors",
            metric=producer_lambda.metric_errors(
                period=Duration.minutes(5)
            ),
            threshold=5,
            evaluation_periods=2,
            alarm_description=f"High error rate in producer Lambda ({self.stage})"
        )

        # Consumer Lambda error rate alarm
        cloudwatch.Alarm(
            self, "ConsumerErrorRateAlarm",
            alarm_name=f"receipt-bot-{self.stage}-consumer-errors",
            metric=consumer_lambda.metric_errors(
                period=Duration.minutes(5)
            ),
            threshold=3,
            evaluation_periods=2,
            alarm_description=f"High error rate in consumer Lambda ({self.stage})"
        )

        # Consumer Lambda duration alarm
        cloudwatch.Alarm(
            self, "ConsumerDurationAlarm",
            alarm_name=f"receipt-bot-{self.stage}-consumer-duration",
            metric=consumer_lambda.metric_duration(
                period=Duration.minutes(5)
            ),
            threshold=Duration.minutes(8).to_milliseconds(),
            evaluation_periods=2,
            alarm_description=f"Consumer Lambda taking too long in {self.stage}"
        )

        cloudwatch.Alarm(
            self, "DeadLetterQueueAlarm",
            alarm_name=f"receipt-bot-{self.stage}-dlq-messages",
            metric=dlq.metric("ApproximateNumberOfVisibleMessages",
                period=Duration.minutes(5),
                statistic="Average"
            ),
            threshold=1,
            evaluation_periods=1,
            alarm_description=f"Messages in dead letter queue - {self.stage} environment"
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
            api_name=f"Receipt Scanner Bot {self.stage.capitalize()} Webhook",
            description=f"Telegram webhook endpoint for receipt scanner bot ({self.stage})"
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
                "stage": "$context.stage",
                "integrationErrorMessage": "$context.integration.error"
            })
        )

        # Ensure the log group can be written to by API Gateway
        log_group.grant_write(iam.ServicePrincipal("apigateway.amazonaws.com"))

        # Add resource-specific tags
        Tags.of(api).add("ResourceType", "ApiGateway")
        Tags.of(api).add("Component", "WebhookEndpoint")

        return api

    def _create_webhook_setup(self, bot_token: str, webhook_url: str, api_gateway: apigwv2.HttpApi, log_group: logs.LogGroup, secret: secretsmanager.Secret) -> None:
        """Create webhook setup custom resource"""

        webhook_lambda = _lambda.Function(
            self, "WebhookSetterHandler",
            function_name=f"receipt-bot-{self.stage}-webhook-setter",
            code=_lambda.Code.from_ecr_image(
                repository=self.lambda_image.repository,
                tag_or_digest=self.lambda_image.asset_hash,
                cmd=["webhook_setter_handler.lambda_handler"]
            ),
            handler=_lambda.Handler.FROM_IMAGE,
            runtime=_lambda.Runtime.FROM_IMAGE,
            timeout=Duration.minutes(2),
            environment={
                "STAGE": self.stage
            },
            log_group=log_group
        )

        # Add resource-specific tags
        Tags.of(webhook_lambda).add("ResourceType", "LambdaFunction")
        Tags.of(webhook_lambda).add("Component", "WebhookSetter")

        secret.grant_read(webhook_lambda)

        # Create custom resource provider
        webhook_provider = cr.Provider(
            self, "WebhookSetterProvider",
            on_event_handler=webhook_lambda
        )

        # Create custom resource
        webhook_setup = CustomResource(
            self, "WebhookSetterResource",
            service_token=webhook_provider.service_token,
            properties={
                'WebhookUrl': webhook_url,
                'Stage': self.stage,
                'BotToken': bot_token
            }
        )

        webhook_setup.node.add_dependency(api_gateway)

    def _create_outputs(self, api_gateway: apigwv2.HttpApi, bucket: s3.Bucket,
                    database: rds.DatabaseInstance, queue: sqs.Queue, bot_token: str,
                    log_group: logs.LogGroup, producer_lambda: _lambda.Function,
                    consumer_lambda: _lambda.Function) -> None:
        """Create stack outputs"""

        CfnOutput(
            self, "TelegramWebhookUrl",
            value=f"{api_gateway.api_endpoint}/webhook",
            description=f"Telegram webhook URL ({self.stage})",
            export_name=f"ReceiptBot-{self.stage.capitalize()}-WebhookUrl"
        )

        CfnOutput(
            self, "ReceiptsBucketName",
            value=bucket.bucket_name,
            description=f"S3 bucket for receipt images ({self.stage})",
            export_name=f"ReceiptBot-{self.stage.capitalize()}-BucketName"
        )

        CfnOutput(
            self, "ProcessingQueueUrl",
            value=queue.queue_url,
            description=f"SQS queue for async message processing ({self.stage})",
            export_name=f"ReceiptBot-{self.stage.capitalize()}-QueueUrl"
        )

        CfnOutput(
            self, "ProcessingQueueName",
            value=queue.queue_name,
            description=f"SQS queue name ({self.stage})",
            export_name=f"ReceiptBot-{self.stage.capitalize()}-QueueName"
        )

        CfnOutput(
            self, "LogGroupName",
            value=log_group.log_group_name,
            description=f"CloudWatch log group ({self.stage})",
            export_name=f"ReceiptBot-{self.stage.capitalize()}-LogGroup"
        )

        CfnOutput(
            self, "ProducerLambdaName",
            value=producer_lambda.function_name,
            description=f"Producer Lambda function name ({self.stage})",
            export_name=f"ReceiptBot-{self.stage.capitalize()}-ProducerLambda"
        )

        CfnOutput(
            self, "ConsumerLambdaName",
            value=consumer_lambda.function_name,
            description=f"Consumer Lambda function name ({self.stage})",
            export_name=f"ReceiptBot-{self.stage.capitalize()}-ConsumerLambda"
        )

        CfnOutput(
            self, "DatabaseEndpoint",
            value=database.instance_endpoint.hostname,
            description=f"RDS PostgreSQL endpoint ({self.stage})",
            export_name=f"ReceiptBot-{self.stage.capitalize()}-DatabaseEndpoint"
        )

        if bot_token != "placeholder_token_for_bootstrap":
            CfnOutput(
                self, "WebhookSetupStatus",
                value=f"Webhook configured automatically for {self.stage}",
                description=f"Webhook setup status ({self.stage})",
                export_name=f"ReceiptBot-{self.stage.capitalize()}-WebhookStatus"
            )
        else:
            CfnOutput(
                self, "WebhookSetupStatus",
                value=f"Set TELEGRAM_BOT_TOKEN and redeploy for {self.stage}",
                description=f"Webhook setup status ({self.stage})",
                export_name=f"ReceiptBot-{self.stage.capitalize()}-WebhookStatus"
            )

    def _create_database_infrastructure(self, app_secret) -> rds.DatabaseInstance:
        """Create publicly accessible RDS PostgreSQL instance with defaults"""

        default_vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)

        # Create security group that allows PostgreSQL access
        db_security_group = ec2.SecurityGroup(
            self, "ReceiptBotDbSecurityGroup",
            security_group_name=f"receipt-bot-{self.stage}-db-sg",
            vpc=default_vpc,
            description=f"Security group for database access ({self.stage})",
            allow_all_outbound=False
        )

        db_security_group.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),  # Allow from anywhere
            connection=ec2.Port.tcp(5432),
            description="PostgreSQL access from internet"
        )

        # Add tags to security group
        Tags.of(db_security_group).add("ResourceType", "SecurityGroup")
        Tags.of(db_security_group).add("Component", "Database")

        database = rds.DatabaseInstance(
            self, "ReceiptBotDatabase",
            instance_identifier=f"receipt-bot-{self.stage}-db",
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
            credentials=rds.Credentials.from_username(
                username=app_secret.secret_value_from_json("DB_USER").unsafe_unwrap(),
                password=app_secret.secret_value_from_json("DB_PASSWORD")
            ),
            allocated_storage=20,
            backup_retention=Duration.days(7) if self.is_production else Duration.days(1),
            deletion_protection=False,
            removal_policy=RemovalPolicy.DESTROY,
            publicly_accessible=True
        )

        # Add resource-specific tags
        Tags.of(database).add("ResourceType", "RDSInstance")
        Tags.of(database).add("Component", "Database")
        Tags.of(database).add("Engine", "PostgreSQL")

        return database

    def _create_database_setup(self, database: rds.DatabaseInstance, log_group: logs.LogGroup) -> None:
        """Create database schema using custom resource"""

        # Create Lambda function for schema initialization from file
        schema_lambda =  _lambda.Function(
            self, "DatabaseSetupHandler",
            function_name=f"receipt-bot-{self.stage}-database-setup",
            code=_lambda.Code.from_ecr_image(
                repository=self.lambda_image.repository,
                tag_or_digest=self.lambda_image.asset_hash,
                cmd=["database_setup_handler.lambda_handler"]
            ),
            handler=_lambda.Handler.FROM_IMAGE,
            runtime=_lambda.Runtime.FROM_IMAGE,
            timeout=Duration.minutes(3),
            memory_size=256,
            environment={
                "DB_HOST": database.instance_endpoint.hostname,
                "DB_USER": SecretValue.unsafe_plain_text('DB_USER').unsafe_unwrap(),
                "DB_PASSWORD": SecretValue.unsafe_plain_text('DB_PASSWORD').unsafe_unwrap(),
                "STAGE": self.stage
            },
            log_group=log_group,
            logging_format=_lambda.LoggingFormat.TEXT,
        )

        # Add resource-specific tags
        Tags.of(schema_lambda).add("ResourceType", "LambdaFunction")
        Tags.of(schema_lambda).add("Component", "SchemaHandler")

        # Create custom resource provider
        schema_provider = cr.Provider(
            self, "DatabaseSetupProvider",
            on_event_handler=schema_lambda
        )

        # Create the custom resource
        schema_resource = CustomResource(
            self, "DatabaseSetupResource",
            service_token=schema_provider.service_token,
            properties={
                'DatabaseEndpoint': database.instance_endpoint.hostname,
                'Stage': self.stage
            }
        )

        # Ensure schema is created after database is ready
        schema_resource.node.add_dependency(database)

    def _create_secrets(self) -> secretsmanager.Secret:
        """Create empty secret for manual population"""
        return secretsmanager.Secret(
            self, "AppSecret",
            secret_name=f"receipt-scanner-bot-{self.stage}",
            description=f"Application secrets for {self.stage}"
            # No initial value - AWS will create empty secret
        )


