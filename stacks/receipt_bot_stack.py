"""
Receipt Bot Stack - AWS CDK Infrastructure
"""
from typing import Dict, Any
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_apigateway as apigateway,
    aws_iam as iam,
    aws_logs as logs,
    CfnOutput
)
from constructs import Construct


class ReceiptBotStack(Stack):
    
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Get bot token from context
        bot_token = self.node.try_get_context("telegram_bot_token")
        if not bot_token:
            raise ValueError("telegram_bot_token must be provided in CDK context")
        
        # Create IAM role for Lambda
        lambda_role = self._create_lambda_role()
        
        # Create Lambda function
        telegram_lambda = self._create_telegram_lambda(lambda_role, bot_token)
        
        # Create API Gateway
        api_gateway = self._create_api_gateway(telegram_lambda)
        
        # Output the webhook URL
        CfnOutput(
            self,
            "TelegramWebhookUrl",
            value=f"{api_gateway.url}webhook",
            description="Telegram webhook URL to configure in BotFather"
        )
    
    def _create_lambda_role(self) -> iam.Role:
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
        
        # Add Bedrock permissions
        role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream"
                ],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
                ]
            )
        )
        
        return role
    
    def _create_telegram_lambda(self, role: iam.Role, bot_token: str) -> _lambda.Function:
        """Create Lambda function for Telegram webhook handling"""
        return _lambda.Function(
            self,
            "TelegramHandler",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="telegram_handler.lambda_handler",
            code=_lambda.Code.from_asset("lambda"),
            role=role,
            timeout=Duration.minutes(5),
            memory_size=512,
            environment={
                "TELEGRAM_BOT_TOKEN": bot_token,
                "BEDROCK_MODEL_ID": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                "AWS_REGION": self.region
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
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
        webhook_integration = apigateway.LambdaIntegration(
            lambda_func,
            request_timeout=Duration.seconds(29)
        )
        
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