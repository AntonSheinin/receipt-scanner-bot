import json
import urllib3
from services.telegram_api import TelegramAPI

http = urllib3.PoolManager()

def lambda_handler(event, context) -> dict:
    """Set or delete Telegram webhook based on CloudFormation event"""
    print(f"Event: {json.dumps(event, default=str)}")

    props = event.get('ResourceProperties', {})
    webhook_url = props.get('WebhookUrl')
    bot_token = props.get('BotToken')
    request_type = event.get('RequestType')

    telegram_bot = TelegramAPI(bot_token)
    response_data = {}
    response_status = "SUCCESS"
    try:
        if request_type in ('Create', 'Update'):
            response_data = telegram_bot.set_webhook(webhook_url)
        elif request_type == 'Delete':
            response_data = telegram_bot.delete_webhook()
    except Exception as e:
        print(f"Error: {e}")
        response_status = "FAILED"
        response_data = {'Error': str(e)}

    send_response(event, context, response_status, response_data)
    return {
        'statusCode': 200,
        'body': json.dumps(response_data)
    }


def send_response(event, context, response_status, response_data) -> None:
    """Send response back to CloudFormation"""
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
    print(f"Response: {json_response}")
    try:
        response = http.request(
            'PUT',
            response_url,
            body=json_response,
            headers={
                'content-type': '',
                'content-length': str(len(json_response))
            }
        )
        print(f"CloudFormation response status: {response.status}")
    except Exception as e:
        print(f"Failed to send response: {e}")