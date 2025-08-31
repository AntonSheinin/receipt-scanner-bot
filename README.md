# Receipt Scanner Bot

A Telegram bot for scanning and analyzing Israeli receipts using AWS serverless infrastructure.

## Version
0.6.0

## Requirements
- Python >= 3.12
- AWS CDK >= 2.150.0
- Node.js 20+ (for CDK)

## Architecture

### Core Components
- **Producer Lambda** (`telegram_bot_handler.py`) - Handles Telegram webhook and queues messages
- **Consumer Lambda** (`consumer_handler.py`) - Processes SQS messages via OrchestratorService
- **Orchestrator Service** - Routes messages by type (photo/text/command) and coordinates processing
- **PostgreSQL Database** - Stores receipt data and analysis results
- **S3 Bucket** - Stores receipt images
- **SQS FIFO Queue** - Message queue for asynchronous processing with deduplication
- **API Gateway HTTP API** - Webhook endpoint for Telegram
- **CloudWatch** - Monitoring, alarms, and centralized logging

### Processing Flow
1. **Webhook Reception**: Producer Lambda receives Telegram updates
2. **Message Queuing**: Messages queued to SQS with deduplication
3. **Message Processing**: Consumer Lambda processes via OrchestratorService
4. **Document Processing**: Multi-strategy approach (LLM/OCR+LLM/Enhanced+OCR+LLM)
5. **Data Validation**: Pydantic schema validation and storage
6. **User Response**: Formatted results sent back via Telegram API

### Services
- **Orchestrator Service** - Main message routing and processing coordination
- **Receipt Service** - End-to-end receipt processing workflow
- **Document Processor Service** - Hybrid OCR/LLM document analysis with strategy pattern
- **Query Service** - Natural language query processing with filter-based retrieval
- **LLM Service** - AI-powered text analysis and structured output generation
- **Message Queue Service** - SQS message queuing for asynchronous processing
- **Telegram Service** - Bot communication and file handling
- **Storage Service** - Database operations and data persistence

## Features

### Receipt Processing
- Supports Israeli receipts in Hebrew
- OCR using Google Vision API or AWS Textract
- LLM analysis using AWS Bedrock (Claude Sonnet 4) or OpenAI GPT models
- Automatic categorization using predefined taxonomy system
- Multi-image receipt support with album processing and image stitching
- Advanced image preprocessing (deskewing, enhancement, grayscale conversion)
- Pydantic-based data validation and schema enforcement
- Receipt limits per user (100 receipts maximum)
- Support for various payment methods and currencies

### Processing Modes
- **LLM Mode**: Direct image analysis using vision-enabled LLMs
- **OCR+LLM Mode**: OCR text extraction followed by LLM structuring
- **Preprocessed+OCR+LLM Mode**: Image enhancement + OCR + LLM analysis

### Deployment & Infrastructure
- Multi-stage deployment (dev/prod)
- AWS CDK Infrastructure as Code
- Docker-based Lambda functions with shared image
- GitHub Actions CI/CD pipeline
- CloudWatch monitoring with custom alarms
- Dead letter queue for failed message handling

### Providers & Utilities
- **Provider Factory** - Creates OCR, LLM, and storage providers
- **Category Manager** - Manages item categorization taxonomy
- **Image Preprocessor** - PIL-based image enhancement for OCR accuracy
- **Helper Utilities** - Security, validation, and response formatting
- **Prompt Manager** - Hebrew/Israeli receipt-specific LLM prompts

## Configuration

### Configuration Details
- **LLM Provider**: `bedrock` (Claude Sonnet 4) or `openai` (GPT models)
- **OCR Provider**: `google_vision` or `aws_textract`
- **Processing Mode**: `llm`, `ocr_llm`, or `pp_ocr_llm`
- **Document Storage**: PostgreSQL with optimized queries
- **Image Storage**: S3 with lifecycle policies

### AWS Resources
- Region: `eu-west-1`
- Database: PostgreSQL 17 on RDS t4g.micro
- Lambda: Python 3.12 runtime
- Storage: S3 + PostgreSQL

## Installation

```bash
# Install CDK dependencies
pip install -e .

# Install AWS CDK
npm install -g aws-cdk@latest
```

## Deployment

```bash
# Deploy to development
cdk deploy --context stage=dev

# Deploy to production
cdk deploy --context stage=prod
```

## Environment Variables
Secrets are managed via AWS Secrets Manager with the following keys:
- `TELEGRAM_BOT_TOKEN`
- `DB_USER`
- `DB_PASSWORD`
- `OPENAI_API_KEY`
- `GOOGLE_CREDENTIALS_JSON`
- `USER_ID_SALT`

