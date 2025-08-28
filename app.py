# Copyright (c) 2025 Anton Sheinin - All rights reserved.
# Unauthorized use is prohibited. See LICENSE file for details.

"""
    Receipt Scanner Bot MVP - CDK App Entry Point
"""

import boto3
import aws_cdk as cdk
from stacks.receipt_scanner_bot_stack import ReceiptScannerBotStack


def main():
    app = cdk.App()

    # Get stage from context (dev or prod)
    stage = app.node.try_get_context("stage")
    if not stage:
        stage = "dev"  # Default to development for safety
        print(f"⚠️  No stage specified. Defaulting to: {stage}")
        print("💡 Use: cdk deploy --context stage=dev|prod")
    else:
        print(f"🎯 Deploying to stage: {stage}")

    # Validate stage
    if stage not in ("dev", "prod"):
        raise ValueError(f"Invalid stage '{stage}'. Must be 'dev' or 'prod'")

    # Create CDK environment
    cdk_env = cdk.Environment(
        account=app.node.try_get_context("account") or boto3.client('sts').get_caller_identity()['Account'],
        region="eu-west-1"
    )

    # Stage-specific stack naming
    stack_name = f"ReceiptScannerBot-{stage.capitalize()}Stack"

    # Common tags for all resources
    common_tags = {
        "App": "receipt-scanner-bot",
        "Stage": stage,
        "Environment": stage,
        "Project": "receipt-scanner-bot",
        "Owner": "development-team",
        "CostCenter": f"receipt-scanner-{stage}",
        "ManagedBy": "aws-cdk"
    }

    # Create the stack with stage awareness
    stack = ReceiptScannerBotStack(
        app,
        stack_name,
        env=cdk_env,
        stage=stage,
        description=f"Receipt Scanner Telegram Bot - {stage.capitalize()} Environment",
        tags=common_tags
    )

    # Apply tags to the stack
    for key, value in common_tags.items():
        cdk.Tags.of(stack).add(key, value)

    # Additional stage-specific tags
    if stage == "prod":
        cdk.Tags.of(stack).add("Backup", "required")
        cdk.Tags.of(stack).add("Monitoring", "critical")
        cdk.Tags.of(stack).add("DataRetention", "long-term")
    else:  # dev
        cdk.Tags.of(stack).add("Backup", "optional")
        cdk.Tags.of(stack).add("Monitoring", "basic")
        cdk.Tags.of(stack).add("DataRetention", "short-term")

    print(f"📋 Stack name: {stack_name}")
    print(f"🏷️ Applied tags: {list(common_tags.keys())}")

    app.synth()

if __name__ == "__main__":
    main()
