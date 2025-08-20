# Copyright (c) 2025 Anton Sheinin - All rights reserved.
# Unauthorized use is prohibited. See LICENSE file for details.

"""
    Receipt Scanner Bot MVP - CDK App Entry Point
"""

import os
from dotenv import load_dotenv
import aws_cdk as cdk
from stacks.receipt_scanner_bot_stack import ReceiptScannerBotStack


# Load environment variables from .env file
load_dotenv()

app = cdk.App()

# Get environment configuration
env = cdk.Environment(
    account=os.getenv("AWS_ACCOUNT_ID") or app.node.try_get_context("account"),
    region=os.getenv("AWS_REGION", "eu-west-1")
)

# Deploy the receipt scanner bot stack
ReceiptScannerBotStack(
    app,
    "ReceiptScannerBotStack",
    env=env,
    description="Receipt Scanner Telegram Bot MVP"
)

app.synth()
