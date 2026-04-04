# AgentWatch CloudFormation Deployment

One-click deployment for AgentWatch AWS CloudWatch Monitoring Agent with Slack integration.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CloudFormation Stack                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐ │
│  │   Slack     │───▶│ API Gateway │───▶│    Lambda Function      │ │
│  │  /ask cmd   │    │  /slack-cmd │    │  (scheduled_monitor)    │ │
│  └─────────────┘    └─────────────┘    └───────────┬─────────────┘ │
│                                                     │               │
│  ┌─────────────┐                                   │               │
│  │ EventBridge │───────────────────────────────────┘               │
│  │ (15 min)    │                                                    │
│  └─────────────┘                                   │               │
│                                                     ▼               │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐ │
│  │  Cognito    │───▶│   OAuth2    │───▶│   AgentCore Runtime     │ │
│  │  User Pool  │    │   Token     │    │   (Bedrock Agent)       │ │
│  └─────────────┘    └─────────────┘    └─────────────────────────┘ │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- AWS CLI configured with appropriate credentials
- Python 3.12+ (for local development helpers)
- Node.js 20+ (for the latest AgentCore CLI)
- Slack App with:
  - Incoming Webhook URL
  - Signing Secret
  - Slash Command capability

## Quick Start

### Option 1: Interactive Script (Recommended)

```bash
cd deployment/cloudformation
./deploy-stack.sh
```

### Option 2: AWS CLI

```bash
aws cloudformation deploy \
  --template-file cloudformation.yaml \
  --stack-name agentwatch \
  --parameter-overrides \
    SlackWebhookUrl="https://hooks.slack.com/services/XXX/YYY/ZZZ" \
    SlackSigningSecret="your-signing-secret" \
    CognitoDomainPrefix="agentwatch-123456" \
  --capabilities CAPABILITY_NAMED_IAM
```

### Option 3: AWS Console

1. Go to **CloudFormation** in AWS Console
2. Click **Create Stack** → **With new resources**
3. Upload `cloudformation.yaml`
4. Fill in parameters
5. Acknowledge IAM capabilities
6. Create stack

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `SlackWebhookUrl` | Yes | Slack incoming webhook URL |
| `SlackSigningSecret` | Yes | Slack app signing secret |
| `CognitoDomainPrefix` | Yes | Unique prefix for Cognito domain (lowercase, alphanumeric) |
| `AgentCoreRuntimeUrl` | No | AgentCore URL (add after AgentCore deployment) |
| `MonitoringSchedule` | No | Schedule frequency (default: 15 minutes) |

## Post-Deployment Steps

### 1. Deploy AgentCore Runtime

```bash
# From project root
python deployment/sync_agentcore_config.py --stack-name agentwatch
./deployment/deploy_agentcore.sh --stack-name agentwatch --wait
```

### 2. Update Stack with AgentCore URL

Fetch the deployed runtime URL:

```bash
# From project root
python get_agent_url.py
```

Then update the stack:

```bash
aws cloudformation update-stack \
  --stack-name agentwatch \
  --use-previous-template \
  --parameters \
    ParameterKey=SlackWebhookUrl,UsePreviousValue=true \
    ParameterKey=SlackSigningSecret,UsePreviousValue=true \
    ParameterKey=CognitoDomainPrefix,UsePreviousValue=true \
    ParameterKey=AgentCoreRuntimeUrl,ParameterValue="YOUR_AGENTCORE_URL" \
  --capabilities CAPABILITY_NAMED_IAM
```

### 3. Configure Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Select your app → **Slash Commands**
3. Create `/ask` command
4. Set Request URL to stack output `SlackCommandEndpoint`

### 4. AgentCore Permissions

The included `agentcore/cdk` project configures the runtime IAM permissions required for CloudWatch, CloudWatch Logs, and STS access. No extra manual policy attachment is required for the default deployment flow.

## Stack Outputs

| Output | Description |
|--------|-------------|
| `SlackCommandEndpoint` | URL for Slack slash command |
| `CognitoDomainUrl` | Cognito OAuth2 endpoint |
| `M2MClientId` | Client ID for authentication |
| `M2MSecretArn` | Secrets Manager ARN for supplemental M2M metadata created by the stack |

## Resources Created

- **Cognito User Pool** - M2M authentication
- **Lambda Function** - Monitoring and Slack integration
- **API Gateway** - Slack slash commands endpoint
- **EventBridge Rule** - Scheduled monitoring (15 min)
- **Secrets Manager** - Supplemental M2M metadata created by the stack
- **IAM Role** - Lambda execution permissions

## Deleting the Stack

```bash
aws cloudformation delete-stack --stack-name agentwatch
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Lambda timeout | Check AgentCore URL, verify Cognito credentials |
| Slack not receiving | Verify webhook URL, check Lambda logs |
| Auth failures | Check the M2M client secret returned by `deploy-stack.sh`, verify Cognito domain and client ID |
| AgentCore errors | Run `./deployment/deploy_agentcore.sh`, then verify `agentcore status` and the runtime URL returned by `python get_agent_url.py` |

## Cost Estimate

~$5-10/month (Lambda, API Gateway, Cognito, EventBridge, Secrets Manager)

*AgentCore runtime costs are separate.*
