"""
Receipt Bot MVP - CDK App Entry Point
"""
import aws_cdk as cdk
from stacks.receipt_bot_stack import ReceiptBotStack

app = cdk.App()

# Get environment configuration
env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region="eu-west-1"
)

# Deploy the receipt bot stack
ReceiptBotStack(
    app, 
    "ReceiptBotStack",
    env=env,
    description="Receipt Recognition Telegram Bot MVP"
)



app.synth()