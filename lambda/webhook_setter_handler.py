import json
import logging
from services.telegram_service import TelegramService
from config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

def lambda_handler(event, context) -> dict:
    """Set or delete Telegram webhook based on CloudFormation event"""
    logger.info(f"Event: {json.dumps(event, default=str)}")

    props = event.get('ResourceProperties', {})
    webhook_url = props.get('WebhookUrl')
    bot_token = props.get('BotToken')
    request_type = event.get('RequestType')

    if not bot_token or bot_token == "placeholder_token_for_bootstrap":
        logger.error("Invalid bot token provided")
        send_response(event, context, "FAILED", {'Error': 'Invalid bot token'})
        return {'statusCode': 400, 'body': json.dumps({'error': 'Invalid bot token'})}

    response_data = {}
    response_status = "SUCCESS"
    
    try:
        # Initialize telegram service (will use BOT_TOKEN from environment)
        telegram_service = TelegramService()
        
        if request_type in ('Create', 'Update'):
            logger.info(f"Setting webhook to: {webhook_url}")
            logger.info(f"Setting commands for bot")

            webhook_response = telegram_service.set_webhook(webhook_url)
            logger.info(f"Webhook response: {webhook_response}")

            commands_response = telegram_service.set_bot_commands()
            logger.info(f"Commands response: {commands_response}")

            if not webhook_response.get('success') or not commands_response.get('success'):
                raise Exception(f"Setup failed - Webhook: {webhook_response}, Commands: {commands_response}")
            
            response_data = {
                'webhook': webhook_response,
                'commands': commands_response,
                'webhook_url': webhook_url
            }
            
        elif request_type == 'Delete':
            logger.info("Deleting webhook")
            response_data = telegram_service.delete_webhook()
            
    except Exception as e:
        logger.critical(f"CRITICAL ERROR in webhook setup: {e}")
        response_status = "FAILED"
        response_data = {'Error': str(e)}

    send_response(event, context, response_status, response_data)
    return {
        'statusCode': 200 if response_status == "SUCCESS" else 500,
        'body': json.dumps(response_data)
    }


def send_response(event, context, response_status, response_data) -> None:
    """Send response back to CloudFormation"""
    import urllib3
    
    response_url = event.get('ResponseURL')
    response_body = {
        'Status': response_status,
        'Reason': f"See CloudWatch Log Stream: {context.log_stream_name}",
        'PhysicalResourceId': context.log_stream_name,
        'StackId': event.get('StackId'),
        'RequestId': event.get('RequestId'),
        'LogicalResourceId': event.get('LogicalResourceId'),
        'Data': response_data
    }
    json_response = json.dumps(response_body)
    logger.info(f"Response: {json_response}")
    
    try:
        http = urllib3.PoolManager()
        response = http.request(
            'PUT',
            response_url,
            body=json_response,
            headers={
                'content-type': '',
                'content-length': str(len(json_response))
            }
        )
        logger.info(f"CloudFormation response status: {response.status}")
    except Exception as e:
        logger.error(f"Failed to send response: {e}")