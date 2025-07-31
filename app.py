"""
Receipt Bot MVP - CDK App Entry Point
"""
import os
from dotenv import load_dotenv
import aws_cdk as cdk
from stacks.receipt_bot_stack import ReceiptBotStack


# Load environment variables from .env file
load_dotenv()

app = cdk.App()

# Get environment configuration
env = cdk.Environment(
    account=app.node.try_get_context("account") or os.getenv("AWS_ACCOUNT_ID"),
    region=os.getenv("AWS_REGION", "eu-west-1")
)

# Deploy the receipt bot stack
ReceiptBotStack(
    app, 
    "ReceiptBotStack",
    env=env,
    description="Receipt Recognition Telegram Bot MVP"
)



app.synth()