# Cognito identity provider

This CDK app creates a Cognito Plus user pool in `us-east-1`, with a replica
in `us-west-2` and Managed Login v2 at `auth.4n6ir.com`. It also configures
regional SES identities, security logs, and a confidential app client for the
Lambda@Edge integration.

## Authentication

- Managed Login requires a password at sign-up. MFA is required: users sign in
  with their password and an authenticator-app code, or with a registered
  passkey that verifies the user. Email OTP is not available as a first
  sign-in factor because Cognito does not support it with required MFA.
- Passkeys must be registered after initial authentication. They are an
  alternative first factor, not a second factor after a password. Managed Login
  prompts users to set up MFA; test enrollment and both sign-in methods before
  using this configuration. Cognito can issue tokens on a new user's first
  sign-in after email confirmation, before an authenticator is enrolled.
  See [Cognito MFA behavior](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-mfa.html).
- Existing users can register a passkey on Cognito's Managed Login
  `/passkeys/add` page after signing in. The application must link or redirect
  them there with an active Managed Login session, its client ID, registered
  redirect URI, and required OAuth parameters. See
  [AWS passkey registration guidance](https://repost.aws/knowledge-center/cognito-passwordless-authentication).
- Existing email-OTP users need a password and an authenticator or a registered
  passkey. Plan their migration before deployment. Have a verified
  administrator recovery process for lost authenticators; Cognito supports
  [resetting a TOTP token](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AdminDeleteSoftwareToken.html).
- Confirmed self-registrations are added to the `DashboardUsers` group. Future
  applications should use their own groups or scopes for authorization rather
  than treating dashboard membership as access to every application.
  The post-confirmation function can use the user pool's KMS key only through
  Cognito. After a failed confirmation trigger, check whether the user was
  confirmed without group membership and repair the membership if needed.
- The confidential `DashboardEdge` client uses the OAuth authorization-code
  flow, refresh token rotation, and the `openid`, `email`, and `profile`
  scopes. Its callbacks are `/callback` and its sign-out URLs are `/` on both
  `https://4n6ir.com` and `https://www.4n6ir.com`.
- Access and ID tokens last 15 minutes; refresh tokens last one day. Managed
  Login SSO can be silently reused for 15 minutes after authentication. A
  refresh token can still renew tokens during its lifetime.
- Session tracking is enabled with Cognito's default limit of 20 active token
  sessions per user. New sign-ins can evict the least recently used session.
  Administrators can list and revoke individual sessions with Cognito APIs;
  the application must implement its own session-management interface.
- The custom domain requires TLS 1.3. Older clients without TLS 1.3 cannot
  connect.

The Lambda@Edge integration must redirect unauthenticated requests to Managed
Login using the confidential `DashboardEdge` client ID, use PKCE, and validate
token signatures, issuer, expiration, token use, and client ID. It must use the
client secret from Secrets Manager when exchanging the authorization code at
the OAuth token endpoint; never expose the secret in a browser. Use the token
endpoint to refresh rotated tokens; `REFRESH_TOKEN_AUTH` is not enabled. Tokens
from both Regions use the updated issuer for the primary Region.

The replicated `credentials` Secrets Manager secret contains project-labeled
credentials in the form
`{"Dashboard":{"CLIENT_ID":"...","CLIENT_SECRET":"..."}}`. The Dashboard
integration must select `Dashboard` before reading these fields. Add future
project entries to the CDK-managed secret; manual changes may be overwritten
by stack updates. All projects in this secret are readable together, not
independently. Cognito replicates the client configuration and secret to the
replica pool as well.

Each Region has three advanced String parameters: `/cognito/secret` contains the
regional secret ARN, `/cognito/encrypt` contains the regional KMS key ARN, and
the non-secret `/cognito/issuer` contains the primary pool's `UpdatedIssuer`.
The issuer is identical in both Regions, including during failover.
Each regional RAM share grants access to those parameters only to the account
in that Region's `/account/domains` parameter. Both account parameters must
contain the same account ID. The secret's resource policy and the regional
KMS key policies separately delegate secret reads and decrypt to that account.
The destination account must grant its edge execution role `ssm:GetParameter`
for the shared parameter ARNs, `secretsmanager:GetSecretValue` for the
regional secret ARNs, and `kms:Decrypt` for the regional key ARNs. Discover
shared parameters with `aws ssm describe-parameters --shared` in each Region;
cross-account `GetParameter` requires the full parameter ARN, not its name.
Accept the RAM invitations if required by the organization configuration.
Restrict secret and key delegation to the role when its ARN is known.

The Domains Lambda should discover `/cognito/issuer` using the same regional
fallback approach as the credentials: read its full shared parameter ARN in
`us-east-1`, falling back to the ARN in `us-west-2` if the primary regional read
fails. Grant its execution role `ssm:GetParameter` for both issuer parameter
ARNs. Use the returned value for token issuer validation; do not switch to a
replica-specific issuer during failover. No secret read or KMS decrypt is needed
to retrieve the issuer.

This changes the existing secret's JSON shape; update any consumer to read
`Dashboard` before deploying the change, and coordinate rollout to avoid
breaking sign-in. There is no Dashboard authentication implementation in this
repository. Advanced parameters and replicated secrets incur regional storage
and API charges.

The secret does not secure CloudFront by itself. The edge integration must
implement authorization-code + PKCE, protect its cookies, validate tokens
and authorization on every protected request, and prevent direct origin
access. It needs the Cognito domain, issuer, callback URLs, and pool ID as
non-secret configuration. Self-registration is enabled and all confirmed
self-registrations join `DashboardUsers`; requiring that group alone does not
restrict access to a pre-approved audience. Secret replication is asynchronous;
test regional reads and failover. Changing Cognito client credentials outside
CDK does not automatically update this stored secret.

## Deployment

Commands use the `cog` AWS profile. Install the CDK CLI and set up the local
Python environment once:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

CDK uses `.venv` automatically; activation is not needed. To diff all stacks,
run `cdk diff --profile cog`. CDK ignores `--all` for `diff` and prints a
warning, but still diffs all stacks when none are specified. Bootstrap
`us-east-1` and `us-west-2` with the `lukach` qualifier if they are not
already bootstrapped.

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
domain prerequisite. Deploy the primary pool and register the replica first:

```sh
cdk deploy --profile cog CognitoIdpStack CognitoReplicaKeyStack CognitoReplicaStack
```

Wait for the primary risk settings to replicate to the secondary before deploying
its regional notification configuration. Compare the output of the following
commands using the `UserPoolId` stack output; the risk actions and templates
must match, although the regional SES source ARN can differ:

```sh
aws cognito-idp describe-risk-configuration --profile cog --region us-east-1 \
  --user-pool-id <user-pool-id>
aws cognito-idp describe-risk-configuration --profile cog --region us-west-2 \
  --user-pool-id <user-pool-id>
```

Replication is eventually consistent. Repeat the comparison before subsequent
updates to risk actions or email templates; the replica only accepts regional
changes to the notification source ARN and sender. The replica stack uses a
custom resource to update the existing replicated configuration, rather than
trying to create another risk attachment. Removing the custom resource does not
reset the replica risk settings. Then deploy:

```sh
cdk deploy --profile cog CognitoReplicaConfigurationStack CognitoCredentialsStack \
  CognitoReplicaCredentialsParametersStack CognitoManagedLoginStack
```

The replica registration stack is in `us-east-1`; its KMS replica key and
regional configuration are in `us-west-2`. Before deployment, confirm that
the `/account/domains` SSM parameter exists in both Regions and contains the
same destination account ID. The credentials stack depends on the replica's
regional key; the replica parameter stack depends on the credentials stack
and regional key. Managed Login depends on the credentials and replica
configuration stacks. Ensure the named `/cognito/*` parameters do not already
belong to another stack before deployment.

### 3. Validate before production

Synthesis is not a live deployment test. Before directing users to the pool:

1. Confirm all stacks completed, the `us-west-2` replica is active, and the
   custom domain and certificate are ready.
2. Test self-registration, confirmation, TOTP enrollment, password plus TOTP,
   passkey registration and sign-in, and assignment to `DashboardUsers`. Verify
   email-OTP-only sign-in is unavailable and test recovery for an authenticator.
   Once the dashboard exists, test both callback URLs, token validation,
   refresh, sign-out, and authorization.
3. Check Cognito security and notification logs in both Regions and test SES
   delivery and feedback.
4. Test automatic failover, replica sign-in and email delivery, and failback.
   Verify that the primary health-check prefix remains primary-specific during
   failover; an override alone does not test detection of an endpoint failure.
5. Test TLS 1.3 client compatibility, session listing and revocation, and
   reauthentication after the SSO and refresh-token limits. Test that the
   verification template also reads correctly for password resets.
6. Confirm both regional RAM shares and the shared parameter values. After the
   Domains account grants its edge role permissions, test reading the
   confidential client secret in both Regions without logging its value,
   confirm the replica is in sync, and test regional read failover. Verify that
   both `/cognito/issuer` parameters equal the primary `UpdatedIssuer` output
   and that the Domains Lambda can read either shared issuer parameter. Test the
   edge authentication, callback, authorization and origin restrictions
   before exposing the dashboard.

Plus threat protection blocks compromised passwords at sign-in, sign-up, and
password change. Low- and medium-risk sign-ins are allowed; high-risk sign-ins
are blocked and the user is emailed with recovery guidance. The pool-wide
settings apply only to clients without their own risk configuration. Check for
client-level overrides and verify the effective configuration in both Regions.
Risk-based MFA requires optional MFA and is not used with required MFA.

Review risk events and false positives before deploying enforcement changes;
AWS recommends at least two weeks of audit data. Switching an enforced pool
to audit mode temporarily removes its automatic protections. Test password
reset, blocked-sign-in notifications, and SES delivery in both Regions. A
blocked compromised password can require a password reset; password resets
are unavailable in the replica during failover. AWS also documents that TOTP
MFA is not supported in secondary replicas, so test and plan access accordingly.
Threat protection is not a rate limiter. Consider AWS WAF and operational
alarms for a public production identity provider. Managed Login automatically
includes device information in security logs; remembered devices are separate
and can bypass MFA, so they are not enabled here.

## Point-in-time recovery

Cognito automatically enables point-in-time recovery for eligible Plus pools,
with up to 14 days of user-data history; no CDK setting is required. Confirm
that recovery is available in the Cognito console. Recoveries are initiated in
the primary Region, pause writes even while the preview is pending, and
replicate restored user data to the replica. Recovery does not restore pool
configuration, app clients, sessions, or remembered devices. See the
[AWS recovery documentation](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-point-in-time-recovery.html)
before initiating one.

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
