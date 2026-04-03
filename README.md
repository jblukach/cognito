# Cognito Multi-Region Authentication

A production-ready AWS CDK infrastructure project that implements multi-region authentication using Amazon Cognito with managed login pages, regional endpoints, and API Gateway integration.

## Overview

This project provides a **highly available**, **geo-distributed** authentication architecture with:

- **Multi-region User Pools** deployed across US regions for redundancy and low-latency access
- **Managed Cognito login pages** with customizable branding
- **Regional API endpoints** for authentication and application logic
- **Lambda Authorizer** integration for secure API access via Bearer tokens
- **Infrastructure-as-Code** using AWS CDK with Python

### Key Features

- 📍 **Multi-Region Deployment** - Independent User Pools in us-east-1, us-east-2, and us-west-2
- 🔐 **Secure Authentication** - Cognito-managed identity and access control
- 🚀 **API Gateway Integration** - Lambda Authorizer for token validation
- 🔑 **Bearer Token Support** - Standards-compliant JWT token handling
- 🔒 **Runtime Secret Retrieval** - Auth and root Lambdas read secrets from Secrets Manager at invocation time
- 🗝️ **KMS-Backed Secret Sharing** - `clientid` is encrypted with customer-managed KMS keys and shared cross-account
- 🏗️ **Infrastructure as Code** - Fully declarative CDK-based infrastructure
- 🏷️ **Public Domain Integration** - Custom domain endpoints (lukach.io)

---

## Architecture

The authentication flow is organized across three main components:

```
User Request
    ↓
Root Endpoint (api.lukach.io)
    ↓
Regional Login Pages
    ├─ hello-use1.lukach.io (US East 1)
    └─ hello-usw2.lukach.io (US West 2)
    ↓
Regional Auth Endpoints
    ├─ use1.api.lukach.io/auth  
    └─ usw2.api.lukach.io/auth
    ↓
Protected API Endpoints
    ├─ use1.api.lukach.io/home (Bearer Token Required)
    └─ usw2.api.lukach.io/home (Bearer Token Required)
```

### Components

- **Root Stack** - Serves as the entry point with domain routing
- **Cognito Stacks** - Regional Cognito User Pool configurations
- **Auth Handlers** - Lambda functions for authentication logic and token validation
- **API Gateway** - Protected endpoints with Lambda Authorizer

---

## Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.9+** or higher
- **AWS CLI** - Configured with appropriate credentials
- **AWS CDK** - Version 2.0 or later
- **AWS Account** - With permissions to create Cognito, API Gateway, Lambda, and Route53 resources

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/jblukach/cognito.git
   cd cognito
   ```

2. Create a Python virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## Project Structure

```
cognito/
├── app.py                           # CDK App entry point
├── requirements.txt                 # Python dependencies
├── cdk.json                         # CDK configuration
├── README.md                        # This file
├── LICENSE                          # License information
│
├── cognito/                         # Cognito stack definitions
│   ├── __init__.py
│   ├── cognito_stackuse1.py         # US East 1 Cognito stack
│   ├── cognito_stackuse2.py         # US East 2 Cognito stack
│   └── cognito_stackusw2.py         # US West 2 Cognito stack
│
├── auth/                            # Lambda authorizer functions
│   ├── authuse1.py                  # Authorizer for US East 1
│   └── authusw2.py                  # Authorizer for US West 2
│
└── root/                            # Root endpoint handlers
    ├── rootuse1.py                  # Root handler for US East 1
    └── rootusw2.py                  # Root handler for US West 2
```

---

## Configuration

### Environment Variables

Set the following environment variables before deployment:

```bash
export CDK_DEFAULT_ACCOUNT=<your-aws-account-id>
export CDK_DEFAULT_REGION=us-east-1
```

### CDK Configuration (cdk.json)

The `cdk.json` file contains CDK context values and feature flags. Key configurations:

- **App Command** - `python3 app.py` (CDK entry point)
- **Watch Patterns** - Files to monitor during development
- **Stack Synthesizer** - Uses custom qualifier 'lukach'

---

## Deployment

### Synthesize the CloudFormation template

```bash
cdk synth
```

This generates CloudFormation templates without deploying them.

### Deploy to AWS

Deploy all stacks:
```bash
cdk deploy --profile cog --all
```

Or deploy specific stacks:
```bash
cdk deploy --profile cog CognitoStackUse1
cdk deploy --profile cog CognitoStackUse2
cdk deploy --profile cog CognitoStackUsw2
```

### Destroy Resources

To tear down the infrastructure:
```bash
cdk destroy --all
```

---

## Usage

### User Authentication Flow

1. User navigates to the root endpoint: `api.lukach.io`
2. User is directed to a regional login page based on preference or proximity
3. User authenticates with Cognito
4. Upon successful authentication, user receives a Bearer token
5. User includes the Bearer token in API requests
6. Lambda Authorizer validates the token
7. If valid, user can access protected endpoints (e.g., `/home`)

### API Request Example

```bash
# Get Bearer Token (via Cognito login)
TOKEN="<bearer-token-from-cognito>"

# Access protected endpoint
curl -H "Authorization: Bearer $TOKEN" \
  https://use1.api.lukach.io/home
```

---

## Development

### Watch Mode

Enable CDK watch mode for automatic redeployment on code changes:

```bash
cdk watch
```

Excluded patterns (see `cdk.json`):
- README.md
- cdk*.json
- requirements*.txt
- `__pycache__` and `__init__.py`
- tests directory

### Stack Tags

All resources are automatically tagged with:

- **Alias**: `cognito`
- **GitHub**: `https://github.com/jblukach/cognito`
- **Org**: `lukach.io`

### Secret Management

- `credentials` secret stores `CLIENT_ID` and `CLIENT_SECRET` for Cognito app clients
- Auth Lambdas receive only `CREDENTIALS_SECRET_ARN` and retrieve secret values from AWS Secrets Manager at runtime
- `clientid` secret stores `CLIENT_ID` for login URL generation
- Root Lambdas receive only `CLIENTID_SECRET_ARN` and retrieve the client ID at runtime
- `clientid` uses customer-managed KMS keys and grants cross-account read/decrypt access to the lunker account

---

## Security Notes

- Cognito User Pools enforce strong password and sign-in controls
- Lambda Authorizer validates incoming API requests
- Bearer tokens use JWT format with expiration times
- Secrets are not injected as plaintext Lambda environment variables
- IAM and key policies are scoped for secret access and cross-account sharing
- Regularly rotate credentials and review IAM permissions

---

## Monitoring & Logging

CloudWatch logs are automatically created for:

- **Cognito** - User authentication events
- **Lambda Functions** - Authorizer and handler execution logs
- **API Gateway** - Request and response logs

Access logs in the AWS Console:
```
AWS CloudWatch → Logs → Log Groups → /aws/lambda/...
```

---

## License

This project is licensed under the [LICENSE](LICENSE) file. See the LICENSE file for details.

---

## Support & Questions

For issues, questions, or contributions, please open an issue on [GitHub](https://github.com/jblukach/cognito).

---

## Related Resources

- [AWS CDK Documentation](https://docs.aws.amazon.com/cdk/)
- [Amazon Cognito Documentation](https://docs.aws.amazon.com/cognito/)
- [API Gateway Lambda Authorizers](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-lambda-function-reuse.html)
- [AWS CLI Reference](https://docs.aws.amazon.com/cli/)
