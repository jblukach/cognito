# Cognito identity provider

This CDK app creates a Cognito Plus user pool in `us-east-1`, with a replica
in `us-west-2` and Managed Login v2 at `auth.4n6ir.com`. It also configures
regional SES identities, security logs, and a public dashboard app client.

## Authentication

- Users can self-register through Managed Login, which requires a password at
  sign-up, and sign in with a password or an email one-time code. **Neither
  is MFA**: Cognito does not support required MFA with native email-OTP
  sign-in, so MFA is disabled for both sign-in methods.
- Confirmed self-registrations are added to the `DashboardUsers` group. Future
  applications should use their own groups or scopes for authorization rather
  than treating dashboard membership as access to every application.
- The public dashboard client uses the OAuth authorization-code flow, refresh
  token rotation, and the `openid`, `email`, and `profile` scopes. Its
  callbacks are `/callback` and its sign-out URLs are `/` on both
  `https://4n6ir.com` and `https://www.4n6ir.com`.

The future dashboard/edge application must implement those URLs, use PKCE, and
validate token signatures, issuer, expiration, token use, and client ID. Use
the OAuth token endpoint to refresh rotated tokens; `REFRESH_TOKEN_AUTH` is
not enabled. Tokens from both Regions use the updated issuer for the primary
Region.

## Deployment

Commands use the `cog` AWS profile. Install the CDK CLI and the Python
dependencies in `requirements.txt`, and activate the Python environment before
running CDK. Bootstrap `us-east-1` and `us-west-2` with the `lukach` qualifier
if they are not already bootstrapped.

### 1. Deploy and verify email

```sh
cdk deploy --profile cog CognitoReplicaSesStack CognitoDomainStack
```

The domain stack manages the public `auth.4n6ir.com` hosted zone, the
`us-east-1` SES identity, and DKIM records for both Regions. The replica SES
identity is a separate stack because SES identities are regional. Confirm that
the stack's hosted zone is authoritative and delegated from `4n6ir.com`; do
not create a duplicate if another zone is already authoritative.

Wait for DNS propagation and verify SES in **both** Regions:

```sh
aws sesv2 get-email-identity --profile cog --region us-east-1 \
  --email-identity auth.4n6ir.com
aws sesv2 get-email-identity --profile cog --region us-west-2 \
  --email-identity auth.4n6ir.com
```

In each response, confirm that `VerificationStatus` and
`DkimAttributes.Status` are `SUCCESS` and `VerifiedForSendingStatus` is
`true`. Also confirm SES production sending access and that sending is enabled
in both Regions:

```sh
aws sesv2 get-account --profile cog --region us-east-1
aws sesv2 get-account --profile cog --region us-west-2
```

Check `ProductionAccessEnabled` and `SendingEnabled`. CloudFormation stack
completion alone does not establish SES verification or production access.

Cognito sends codes from `no-reply@auth.4n6ir.com` with replies to
`hello@4n6ir.com`. SES publishes bounce and complaint events to regional SNS
topics, which send JSON notifications to that reply address. The stacks do not
create an inbox. **Confirm both SNS subscription emails**, one per Region, and
test both feedback paths before production; CloudFormation does not wait for
subscription confirmation.

### 2. Deploy Cognito

Ensure `4n6ir.com` has a publicly resolvable A record for the Cognito custom
domain prerequisite. Then deploy:

```sh
cdk deploy --profile cog CognitoIdpStack CognitoReplicaKeyStack CognitoReplicaStack \
  CognitoReplicaConfigurationStack CognitoManagedLoginStack
```

The replica registration stack is in `us-east-1`; its KMS replica key and
regional configuration are in `us-west-2`. The Managed Login stack depends on
the replica configuration so domain failover is configured after activation.

### 3. Validate before production

Synthesis is not a live deployment test. Before directing users to the pool:

1. Confirm all stacks completed, the `us-west-2` replica is active, and the
   custom domain and certificate are ready.
2. Test self-registration, confirmation, password and email-OTP sign-in, and
   assignment to `DashboardUsers`. Once the dashboard exists, test both callback
   URLs, token validation, refresh, sign-out, and authorization.
3. Check Cognito security and notification logs in both Regions and test SES
   delivery and feedback.
4. Test automatic failover, replica sign-in and email delivery, and failback.
   Verify that the primary health-check prefix remains primary-specific during
   failover; an override alone does not test detection of an endpoint failure.

Plus threat protection is enabled, but password-specific protections do not
apply to email-OTP sign-in. Verify the protection and logs available for both
flows. Threat protection is not a rate limiter; consider AWS WAF and
operational alarms for a public production identity provider.

## Regional failover

The Route 53 health check requests the primary Region's separate Cognito prefix
domain login page every 30 seconds, with a threshold of three failures. Cognito
uses the health status to route `auth.4n6ir.com` to the replica and back; the
Route 53 alias records themselves are not failover records.

This is an HTTPS availability check, not an end-to-end sign-in or email test.
Route 53 accepts both 2xx and 3xx responses, including redirects. Detection and
routing take time, and three failures do not guarantee a 90-second failover.
The prefix includes the account ID for uniqueness but may still conflict with
an existing Cognito domain.

The standard 30-second interval avoids the higher-cost fast interval.
[Route 53 pricing](https://aws.amazon.com/route53/pricing/) lists a base charge
and an HTTPS feature charge. Confirm Cognito endpoint eligibility for the
free allowance and the actual charge with AWS billing.

The secondary can authenticate existing users but cannot create users, reset
passwords, or update profiles. It is not a writable primary. Replication is
eventually consistent, so recent changes might not have arrived. Applications
calling Cognito APIs directly need their own regional routing.

### Manual override and failback

Automatic routing is the default. If a user-impacting issue is not detected by
the check, an operator can temporarily force Managed Login to `us-west-2`. Test
this procedure before production. The same custom domain is used in both
Regions; DNS alone does not establish which Region served a sign-in.

1. Get the health-check ID and inspect its configuration:

   ```sh
   HEALTH_CHECK_ID=$(aws cloudformation describe-stacks --profile cog \
     --region us-east-1 --stack-name CognitoManagedLoginStack \
     --query "Stacks[0].Outputs[?OutputKey=='FailoverHealthCheckId'].OutputValue | [0]" \
     --output text)
   aws route53 get-health-check --profile cog --health-check-id "$HEALTH_CHECK_ID"
   ```

   Confirm the ID, hostname, and Cognito domain's routing configuration before
   proceeding. Do not use an empty or `None` ID.

2. Force the check unhealthy to request routing to `us-west-2`:

   ```sh
   aws route53 update-health-check --profile cog --health-check-id "$HEALTH_CHECK_ID" \
     --disabled --inverted
   ```

   A disabled endpoint check is considered healthy, so inversion is also
   required. Check the settings and Route 53 health status, then test sign-in
   for an existing user. Use regional logs or metrics where available to
   corroborate routing. Propagation is not instantaneous.

3. When `us-east-1` is healthy, restore automatic monitoring:

   ```sh
   aws route53 update-health-check --profile cog --health-check-id "$HEALTH_CHECK_ID" \
     --no-disabled --no-inverted
   ```

   Verify the settings and health status, then test sign-in and confirm
   failback. A healthy check alone does not prove authentication or email works.

The override changes a CDK-managed resource outside CloudFormation. Avoid
deployments while it is active, restore both settings afterward, and check for
drift. Disabled health checks continue to incur charges.
