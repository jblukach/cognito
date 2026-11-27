import json

from aws_cdk import (
    Acknowledgment,
    ArnFormat,
    Aws,
    CfnOutput,
    Duration,
    Fn,
    RemovalPolicy,
    SecretValue,
    Stack,
    Validations,
    aws_certificatemanager as _acm,
    aws_cognito as _cognito,
    aws_iam as _iam,
    aws_kms as _kms,
    aws_lambda as _lambda,
    aws_logs as _logs,
    aws_ram as _ram,
    aws_route53 as _route53,
    aws_route53_targets as _route53_targets,
    aws_secretsmanager as _secrets,
    aws_ssm as _ssm,
)
from constructs import Construct

from cognito.cognito_domain import AUTH_DOMAIN, EMAIL_REPLY_TO_ADDRESS

EMAIL_IDENTITY_DOMAIN = AUTH_DOMAIN
EMAIL_FROM_ADDRESS = "no-reply@auth.4n6ir.com"
REPLICA_REGION = "us-west-2"
LOG_RETENTION = _logs.RetentionDays.THIRTEEN_MONTHS
DOMAINS_ACCOUNT_PARAMETER = "/account/domains"


def _credentials_key(scope: Stack) -> _kms.Key:
    domains_account = _ssm.StringParameter.value_for_string_parameter(
        scope, DOMAINS_ACCOUNT_PARAMETER
    )
    key = _kms.Key(
        scope,
        "CredentialsKey",
        description="Encrypts regional CloudFront Cognito credentials",
        enable_key_rotation=True,
        removal_policy=RemovalPolicy.RETAIN,
    )
    key.add_to_resource_policy(
        _iam.PolicyStatement(
            principals=[_iam.AccountPrincipal(domains_account)],
            actions=["kms:Decrypt"],
            resources=["*"],
            conditions={
                "StringEquals": {
                    "kms:ViaService": f"secretsmanager.{scope.region}.{Aws.URL_SUFFIX}",
                },
                "StringLike": {
                    "kms:EncryptionContext:SecretARN": scope.format_arn(
                        service="secretsmanager", resource="secret",
                        resource_name="credentials-*",
                        arn_format=ArnFormat.COLON_RESOURCE_NAME,
                    ),
                },
            },
        )
    )
    return key


def _share_credentials_parameters(
    scope: Stack, secret_arn: str, key_arn: str
) -> None:
    domains_account = _ssm.StringParameter.value_for_string_parameter(
        scope, DOMAINS_ACCOUNT_PARAMETER
    )
    parameters = [
        _ssm.StringParameter(
            scope,
            construct_id,
            parameter_name=name,
            string_value=value,
            tier=_ssm.ParameterTier.ADVANCED,
        )
        for construct_id, name, value in (
            ("CredentialsKeyParameter", "/cognito/encrypt", key_arn),
            ("CredentialsSecretParameter", "/cognito/secret", secret_arn),
        )
    ]
    share = _ram.CfnResourceShare(
        scope,
        "CredentialsParameterShare",
        name="cognito-credentials",
        principals=[domains_account],
        resource_arns=[parameter.parameter_arn for parameter in parameters],
    )
    for parameter in parameters:
        share.node.add_dependency(parameter)


def _key_policy(account: str, regions: list[str]) -> dict:
    user_pool_arns = [
        f"arn:{Aws.PARTITION}:cognito-idp:{region}:{account}:userpool/*"
        for region in regions
    ]
    statements = [
        {
            "Sid": "AllowAccountAdministration",
            "Effect": "Allow",
            "Principal": {"AWS": f"arn:{Aws.PARTITION}:iam::{account}:root"},
            "Action": "kms:*",
            "Resource": "*",
        }
    ]

    for region, user_pool_arn in zip(regions, user_pool_arns):
        logs_arn = f"arn:{Aws.PARTITION}:logs:{region}:{account}:*"
        cognito_conditions = {
            "ArnLike": {"aws:SourceArn": user_pool_arn},
            "StringEquals": {"aws:SourceAccount": account},
        }

        statements.extend(
            [
                {
                    "Sid": f"AllowCognitoUserPoolEncryption{region.replace('-', '')}",
                    "Effect": "Allow",
                    "Principal": {
                        "Service": [
                            "cognito-idp.amazonaws.com",
                            "identitystore.amazonaws.com",
                        ]
                    },
                    "Action": [
                        "kms:Encrypt",
                        "kms:Decrypt",
                        "kms:ReEncrypt*",
                        "kms:GenerateDataKeyWithoutPlainText",
                    ],
                    "Resource": "*",
                    "Condition": {
                        **cognito_conditions,
                        "StringLike": {
                            "kms:EncryptionContext:aws:cognito-idp:userpool-arn": user_pool_arns
                        },
                    },
                },
                {
                    "Sid": f"AllowCognitoDescribeKey{region.replace('-', '')}",
                    "Effect": "Allow",
                    "Principal": {
                        "Service": [
                            "cognito-idp.amazonaws.com",
                            "identitystore.amazonaws.com",
                        ]
                    },
                    "Action": "kms:DescribeKey",
                    "Resource": "*",
                    "Condition": cognito_conditions,
                },
                {
                    "Sid": f"AllowCognitoLogExport{region.replace('-', '')}",
                    "Effect": "Allow",
                    "Principal": {"Service": "cognito-idp.amazonaws.com"},
                    "Action": ["kms:GenerateDataKey", "kms:Encrypt"],
                    "Resource": "*",
                    "Condition": {
                        "StringLike": {"kms:EncryptionContext:SourceArn": logs_arn}
                    },
                },
                {
                    "Sid": f"AllowCloudWatchLogDelivery{region.replace('-', '')}",
                    "Effect": "Allow",
                    "Principal": {"Service": "delivery.logs.amazonaws.com"},
                    "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
                    "Resource": "*",
                    "Condition": {
                        "StringLike": {"kms:EncryptionContext:SourceArn": logs_arn}
                    },
                },
            ]
        )

    return {"Version": "2012-10-17", "Statement": statements}


def _add_log_delivery(
    scope: Construct,
    user_pool_id: str,
    region: str,
    suffix: str,
) -> tuple[_logs.LogGroup, _cognito.CfnLogDeliveryConfiguration]:
    log_group = _logs.LogGroup(
        scope,
        f"UserPoolSecurityLogs{suffix}",
        log_group_name=f"/aws/cognito/user-pool/4n6ir/{suffix.lower()}",
        retention=LOG_RETENTION,
        removal_policy=RemovalPolicy.RETAIN,
    )
    log_group_arn = (
        f"arn:{Aws.PARTITION}:logs:{region}:{Stack.of(scope).account}:"
        f"log-group:{log_group.log_group_name}"
    )

    resource_policy = _logs.CfnResourcePolicy(
        scope,
        f"UserPoolLogDeliveryPolicy{suffix}",
        policy_document=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "delivery.logs.amazonaws.com"
                        },
                        "Action": [
                            "logs:CreateLogStream",
                            "logs:PutLogEvents",
                        ],
                        "Resource": f"{log_group_arn}:*",
                        "Condition": {
                            "StringEquals": {
                                "aws:SourceAccount": Stack.of(scope).account
                            },
                            "ArnLike": {
                                "aws:SourceArn": (
                                    f"arn:{Aws.PARTITION}:logs:{region}:"
                                    f"{Stack.of(scope).account}:*"
                                )
                            },
                        },
                    }
                ],
            }
        ),
        policy_name=f"CognitoLogDelivery{suffix}",
    )

    log_delivery = _cognito.CfnLogDeliveryConfiguration(
        scope,
        f"UserPoolLogDelivery{suffix}",
        user_pool_id=user_pool_id,
        log_configurations=[
            _cognito.CfnLogDeliveryConfiguration.LogConfigurationProperty(
                cloud_watch_logs_configuration=(
                    _cognito.CfnLogDeliveryConfiguration.CloudWatchLogsConfigurationProperty(
                        log_group_arn=log_group_arn
                    )
                ),
                event_source="userAuthEvents",
                log_level="INFO",
            ),
            _cognito.CfnLogDeliveryConfiguration.LogConfigurationProperty(
                cloud_watch_logs_configuration=(
                    _cognito.CfnLogDeliveryConfiguration.CloudWatchLogsConfigurationProperty(
                        log_group_arn=log_group_arn
                    )
                ),
                event_source="userNotification",
                log_level="ERROR",
            ),
        ],
    )
    log_delivery.add_resource_dependency(resource_policy)
    return log_group, log_delivery


class CognitoIdpStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        ses_identity_arn: str,
        ses_configuration_set: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        account = Stack.of(self).account

        encryption_key = _kms.CfnKey(
            self,
            "UserPoolEncryptionKey",
            description="Multi-Region encryption key for the 4n6ir Cognito user pool",
            key_policy=_key_policy(account, ["us-east-1", REPLICA_REGION]),
            key_spec="SYMMETRIC_DEFAULT",
            key_usage="ENCRYPT_DECRYPT",
            multi_region=True,
            enable_key_rotation=True,
            pending_window_in_days=30,
        )
        encryption_key.apply_removal_policy(RemovalPolicy.RETAIN)
        self.encryption_key = encryption_key

        confirmation_lambda = _lambda.Function(
            self,
            "AssignDashboardBirthright",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="index.handler",
            timeout=Duration.seconds(10),
            code=_lambda.Code.from_inline(
                "import boto3\n"
                "client = boto3.client('cognito-idp')\n"
                "def handler(event, context):\n"
                "    if event['triggerSource'] == 'PostConfirmation_ConfirmSignUp':\n"
                "        client.admin_add_user_to_group(\n"
                "            UserPoolId=event['userPoolId'],\n"
                "            Username=event['userName'],\n"
                "            GroupName='DashboardUsers',\n"
                "        )\n"
                "    return event\n"
            ),
        )
        confirmation_lambda.add_to_role_policy(
            _iam.PolicyStatement(
                actions=["cognito-idp:AdminAddUserToGroup"],
                resources=[
                    Stack.of(self).format_arn(
                        service="cognito-idp",
                        resource="userpool/*",
                    )
                ],
            )
        )

        user_pool = _cognito.CfnUserPool(
            self,
            "UserPool",
            user_pool_name="4n6ir",
            user_pool_tier="PLUS",
            deletion_protection="ACTIVE",
            username_attributes=["email"],
            username_configuration=_cognito.CfnUserPool.UsernameConfigurationProperty(
                case_sensitive=False
            ),
            auto_verified_attributes=["email"],
            admin_create_user_config=(
                _cognito.CfnUserPool.AdminCreateUserConfigProperty(
                    allow_admin_create_user_only=False
                )
            ),
            policies=_cognito.CfnUserPool.PoliciesProperty(
                sign_in_policy=_cognito.CfnUserPool.SignInPolicyProperty(
                    allowed_first_auth_factors=["PASSWORD", "WEB_AUTHN"]
                )
            ),
            email_configuration=_cognito.CfnUserPool.EmailConfigurationProperty(
                email_sending_account="DEVELOPER",
                configuration_set=ses_configuration_set,
                from_=EMAIL_FROM_ADDRESS,
                reply_to_email_address=EMAIL_REPLY_TO_ADDRESS,
                source_arn=ses_identity_arn,
            ),
            verification_message_template=(
                _cognito.CfnUserPool.VerificationMessageTemplateProperty(
                    default_email_option="CONFIRM_WITH_CODE",
                    email_subject="Confirm your 4n6ir account",
                    email_message=(
                        "Your 4n6ir verification code is <strong>{####}</strong>."
                        "<br><br>Enter this code to continue. Never share it with anyone."
                        "<br><br>If you didn't request this code, you can ignore this email."
                    ),
                )
            ),
            mfa_configuration="ON",
            enabled_mfas=["SOFTWARE_TOKEN_MFA"],
            web_authn_factor_configuration="MULTI_FACTOR_WITH_USER_VERIFICATION",
            web_authn_relying_party_id=AUTH_DOMAIN,
            web_authn_user_verification="required",
            key_configuration=_cognito.CfnUserPool.KeyConfigurationProperty(
                key_type="CUSTOMER_MANAGED_KEY",
                kms_key_arn=encryption_key.attr_arn,
            ),
            issuer_configuration=_cognito.CfnUserPool.IssuerConfigurationProperty(
                type="UPDATED"
            ),
            user_pool_add_ons=_cognito.CfnUserPool.UserPoolAddOnsProperty(
                advanced_security_mode="ENFORCED"
            ),
            user_pool_tags={"Application": "4n6ir", "Purpose": "CentralIdP"},
            lambda_config=_cognito.CfnUserPool.LambdaConfigProperty(
                post_confirmation=confirmation_lambda.function_arn
            ),
        )
        user_pool.apply_removal_policy(RemovalPolicy.RETAIN)
        self.user_pool = user_pool

        confirmation_lambda.add_to_role_policy(
            _iam.PolicyStatement(
                actions=[
                    "kms:Encrypt",
                    "kms:Decrypt",
                    "kms:ReEncrypt*",
                    "kms:GenerateDataKeyWithoutPlainText",
                ],
                resources=[encryption_key.attr_arn],
                conditions={
                    "StringEquals": {
                        "kms:ViaService": f"cognito-idp.{self.region}.{Aws.URL_SUFFIX}",
                    },
                    "StringLike": {
                        "kms:EncryptionContext:aws:cognito-idp:userpool-arn": (
                            Stack.of(self).format_arn(
                                service="cognito-idp", resource="userpool/*"
                            )
                        ),
                    },
                },
            )
        )
        confirmation_lambda.add_to_role_policy(
            _iam.PolicyStatement(
                actions=["kms:DescribeKey"],
                resources=[encryption_key.attr_arn],
                conditions={
                    "StringEquals": {
                        "kms:ViaService": f"cognito-idp.{self.region}.{Aws.URL_SUFFIX}",
                    },
                },
            )
        )

        confirmation_lambda.add_permission(
            "AllowCognitoPostConfirmation",
            principal=_iam.ServicePrincipal("cognito-idp.amazonaws.com"),
            source_arn=user_pool.attr_arn,
            source_account=account,
        )

        _cognito.CfnUserPoolGroup(
            self,
            "DashboardUsersGroup",
            user_pool_id=user_pool.ref,
            group_name="DashboardUsers",
            description="Birthright access for self-registered dashboard users",
        )

        session_tracking = _cognito.CfnUserPoolSessionConfigurationAttachment(
            self,
            "UserPoolSessionTracking",
            user_pool_id=user_pool.ref,
            user_session_tracking="ENABLED",
            token_session=(
                _cognito.CfnUserPoolSessionConfigurationAttachment.TokenSessionProperty(
                    max_per_user=20
                )
            ),
        )
        Validations.of(session_tracking).acknowledge(
            Acknowledgment(
                id="CloudFormation-Validate::F3006",
                reason="The Cognito session resource is live in CloudFormation; CDK's bundled schema is stale.",
            )
        )

        log_group, _ = _add_log_delivery(
            self, user_pool.ref, "us-east-1", "Primary"
        )

        CfnOutput(self, "UserPoolId", value=user_pool.ref)
        CfnOutput(
            self,
            "UpdatedIssuer",
            value=f"https://issuer-cognito-idp.us-east-1.amazonaws.com/{user_pool.ref}",
        )
        CfnOutput(self, "PrimarySecurityLogGroup", value=log_group.log_group_name)
        CfnOutput(self, "SesEmailIdentity", value=EMAIL_IDENTITY_DOMAIN)


class CognitoReplicaKeyStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        primary_encryption_key: _kms.CfnKey,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        account = Stack.of(self).account

        replica_key = _kms.CfnReplicaKey(
            self,
            "UserPoolEncryptionKeyReplica",
            primary_key_arn=primary_encryption_key.attr_arn,
            key_policy=_key_policy(account, ["us-east-1", REPLICA_REGION]),
            description="Replica KMS key for the 4n6ir Cognito user pool",
        )
        replica_key.apply_removal_policy(RemovalPolicy.RETAIN)
        self.replica_key = replica_key

        CfnOutput(
            self,
            "ReplicaKmsKeyArn",
            value=replica_key.attr_arn,
        )


class CognitoReplicaStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        primary_user_pool: _cognito.CfnUserPool,
        replica_key_stack: CognitoReplicaKeyStack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.add_stack_dependency(replica_key_stack)
        replica = _cognito.CfnUserPoolReplica(
            self,
            "UserPoolReplica",
            user_pool_id=primary_user_pool.ref,
            region_name=REPLICA_REGION,
            user_pool_tags_at_create={
                "Application": "4n6ir",
                "Purpose": "CentralIdP",
            },
        )
        self.replica = replica

        CfnOutput(self, "ReplicaUserPoolId", value=primary_user_pool.ref)


class CognitoReplicaConfigurationStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        primary_user_pool: _cognito.CfnUserPool,
        ses_identity_arn: str,
        ses_configuration_set: str,
        replica_key_stack: CognitoReplicaKeyStack,
        replica_registration_stack: CognitoReplicaStack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.add_stack_dependency(replica_key_stack)
        self.add_stack_dependency(replica_registration_stack)
        self.credentials_key = _credentials_key(self)
        regional_configuration = (
            _cognito.CfnUserPoolRegionalConfigurationAttachment(
                self,
                "UserPoolReplicaConfiguration",
                user_pool_id=primary_user_pool.ref,
                status="ACTIVE",
                email_configuration=(
                    _cognito.CfnUserPoolRegionalConfigurationAttachment.EmailConfigurationProperty(
                        email_sending_account="DEVELOPER",
                        configuration_set=ses_configuration_set,
                        from_=EMAIL_FROM_ADDRESS,
                        reply_to_email_address=EMAIL_REPLY_TO_ADDRESS,
                        source_arn=ses_identity_arn,
                    )
                ),
                user_pool_tags={
                    "Application": "4n6ir",
                    "Purpose": "CentralIdP",
                },
            )
        )

        log_group, log_delivery = _add_log_delivery(
            self, primary_user_pool.ref, REPLICA_REGION, "Replica"
        )
        log_delivery.add_resource_dependency(regional_configuration)

        CfnOutput(self, "ReplicaUserPoolId", value=primary_user_pool.ref)
        CfnOutput(
            self,
            "ReplicaUpdatedIssuer",
            value=(
                f"https://issuer-cognito-idp.{Stack.of(primary_user_pool).region}.amazonaws.com/"
                f"{primary_user_pool.ref}"
            ),
        )
        CfnOutput(self, "ReplicaSecurityLogGroup", value=log_group.log_group_name)
        CfnOutput(self, "ReplicaCredentialsKeyArn", value=self.credentials_key.key_arn)


class CognitoCredentialsStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        user_pool: _cognito.CfnUserPool,
        replica_credentials_key: _kms.IKey,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        domains_account = _ssm.StringParameter.value_for_string_parameter(
            self, DOMAINS_ACCOUNT_PARAMETER
        )
        edge_client = _cognito.CfnUserPoolClient(
            self,
            "EdgeAppClient",
            user_pool_id=user_pool.ref,
            client_name="DashboardEdge",
            generate_secret=True,
            explicit_auth_flows=["ALLOW_USER_AUTH"],
            allowed_o_auth_flows=["code"],
            allowed_o_auth_flows_user_pool_client=True,
            allowed_o_auth_scopes=["openid", "email", "profile"],
            callback_ur_ls=[
                "https://4n6ir.com/callback",
                "https://www.4n6ir.com/callback",
            ],
            logout_ur_ls=["https://4n6ir.com/", "https://www.4n6ir.com/"],
            supported_identity_providers=["COGNITO"],
            enable_token_revocation=True,
            prevent_user_existence_errors="ENABLED",
            access_token_validity=15,
            id_token_validity=15,
            refresh_token_validity=1,
            token_validity_units=_cognito.CfnUserPoolClient.TokenValidityUnitsProperty(
                access_token="minutes", id_token="minutes", refresh_token="days"
            ),
            refresh_token_rotation=(
                _cognito.CfnUserPoolClient.RefreshTokenRotationProperty(
                    feature="ENABLED", retry_grace_period_seconds=5
                )
            ),
        )
        self.edge_client = edge_client
        edge_session = _cognito.CfnUserPoolClientSessionConfigurationAttachment(
            self,
            "EdgeClientSession",
            user_pool_id=user_pool.ref,
            client_id=edge_client.ref,
            sso_session=(
                _cognito.CfnUserPoolClientSessionConfigurationAttachment.SSOSessionProperty(
                    max_validity_minutes=15
                )
            ),
        )
        Validations.of(edge_session).acknowledge(
            Acknowledgment(
                id="CloudFormation-Validate::F3006",
                reason="The Cognito session resource is live in CloudFormation; CDK's bundled schema is stale.",
            )
        )
        key = _credentials_key(self)
        credentials = _secrets.Secret(
            self,
            "Credentials",
            secret_name="credentials",
            encryption_key=key,
            removal_policy=RemovalPolicy.RETAIN,
            secret_string_value=SecretValue.unsafe_plain_text(
                self.to_json_string({
                    "Dashboard": {
                        "CLIENT_ID": edge_client.ref,
                        "CLIENT_SECRET": edge_client.attr_client_secret,
                    },
                })
            ),
            replica_regions=[
                _secrets.ReplicaRegion(
                    region=REPLICA_REGION,
                    encryption_key=replica_credentials_key,
                )
            ],
        )
        credentials.add_to_resource_policy(
            _iam.PolicyStatement(
                principals=[_iam.AccountPrincipal(domains_account)],
                actions=["secretsmanager:GetSecretValue"],
                resources=["*"],
            )
        )
        self.credentials = credentials
        _share_credentials_parameters(self, credentials.secret_arn, key.key_arn)
        CfnOutput(self, "CredentialsSecretArn", value=credentials.secret_arn)
        CfnOutput(self, "CredentialsKeyArn", value=key.key_arn)


class CognitoReplicaCredentialsParametersStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        credentials: _secrets.ISecret,
        replica_credentials_key: _kms.IKey,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        replica_secret_arn = self.format_arn(
            service="secretsmanager",
            resource="secret",
            resource_name=Fn.select(6, Fn.split(":", credentials.secret_arn)),
            arn_format=ArnFormat.COLON_RESOURCE_NAME,
        )
        _share_credentials_parameters(
            self, replica_secret_arn, replica_credentials_key.key_arn
        )


class CognitoManagedLoginStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        hosted_zone: _route53.IHostedZone,
        user_pool: _cognito.CfnUserPool,
        edge_client: _cognito.CfnUserPoolClient,
        replica_configuration_stack: CognitoReplicaConfigurationStack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.add_stack_dependency(replica_configuration_stack)

        certificate = _acm.Certificate(
            self,
            "ManagedLoginCertificate",
            domain_name=AUTH_DOMAIN,
            validation=_acm.CertificateValidation.from_dns(hosted_zone),
        )
        primary_domain = _cognito.CfnUserPoolDomain(
            self,
            "PrimaryHealthCheckDomain",
            domain=f"4n6ir-primary-health-{Aws.ACCOUNT_ID}",
            user_pool_id=user_pool.ref,
            managed_login_version=2,
        )
        health_check = _route53.HealthCheck(
            self,
            "ManagedLoginHealthCheck",
            type=_route53.HealthCheckType.HTTPS,
            fqdn=f"{primary_domain.ref}.auth.{Aws.REGION}.amazoncognito.com",
            port=443,
            resource_path=(
                f"/login?response_type=code&client_id={edge_client.ref}"
                "&redirect_uri=https%3A%2F%2F4n6ir.com%2Fcallback"
            ),
            request_interval=Duration.seconds(30),
            failure_threshold=3,
        )
        domain = _cognito.CfnUserPoolDomain(
            self,
            "ManagedLoginDomain",
            domain=AUTH_DOMAIN,
            user_pool_id=user_pool.ref,
            managed_login_version=2,
            custom_domain_config=(
                _cognito.CfnUserPoolDomain.CustomDomainConfigTypeProperty(
                    certificate_arn=certificate.certificate_arn,
                    security_policy="TLS_V1_3_2025",
                )
            ),
            routing=_cognito.CfnUserPoolDomain.RoutingTypeProperty(
                failover=_cognito.CfnUserPoolDomain.FailoverTypeProperty(
                    primary_route53_health_check_id=health_check.health_check_id,
                    secondary_region=REPLICA_REGION,
                )
            ),
        )
        domain.add_resource_dependency(edge_client)

        for record_type in ("A", "AAAA"):
            _route53.CfnRecordSet(
                self,
                f"ManagedLogin{record_type}Record",
                hosted_zone_id=hosted_zone.hosted_zone_id,
                name=AUTH_DOMAIN,
                type=record_type,
                alias_target=_route53.CfnRecordSet.AliasTargetProperty(
                    dns_name=domain.attr_cloud_front_distribution,
                    hosted_zone_id=_route53_targets.CloudFrontTarget.get_hosted_zone_id(
                        self
                    ),
                    evaluate_target_health=False,
                ),
            )

        branding = _cognito.CfnManagedLoginBranding(
            self,
            "EdgeManagedLoginBranding",
            user_pool_id=user_pool.ref,
            client_id=edge_client.ref,
            use_cognito_provided_values=False,
            settings={
                "categories": {
                    "form": {
                        "displayGraphics": True,
                        "location": {
                            "horizontal": "CENTER",
                            "vertical": "CENTER",
                        },
                    },
                    "global": {
                        "colorSchemeMode": "LIGHT",
                        "spacingDensity": "REGULAR",
                    },
                },
                "componentClasses": {
                    "buttons": {"borderRadius": 8.0},
                    "focusState": {
                        "lightMode": {"borderColor": "0972d3ff"}
                    },
                    "link": {
                        "lightMode": {
                            "defaults": {"textColor": "1b5e20ff"},
                            "hover": {"textColor": "2e7d32ff"},
                        }
                    },
                },
                "components": {
                    "form": {
                        "borderRadius": 12.0,
                        "lightMode": {
                            "backgroundColor": "ffffffff",
                            "borderColor": "bdefcaff",
                        },
                    },
                    "pageBackground": {
                        "image": {"enabled": False},
                        "lightMode": {"color": "bdefcaff"},
                    },
                    "pageHeader": {
                        "lightMode": {
                            "background": {"color": "ffffffff"},
                            "borderColor": "ffffffff",
                        },
                        "logo": {"enabled": False, "location": "START"},
                    },
                    "pageText": {
                        "lightMode": {
                            "bodyColor": "33443aff",
                            "descriptionColor": "516258ff",
                            "headingColor": "172b1bff",
                        }
                    },
                    "primaryButton": {
                        "lightMode": {
                            "active": {
                                "backgroundColor": "033160ff",
                                "textColor": "ffffffff",
                            },
                            "defaults": {
                                "backgroundColor": "0972d3ff",
                                "textColor": "ffffffff",
                            },
                            "hover": {
                                "backgroundColor": "033160ff",
                                "textColor": "ffffffff",
                            },
                        }
                    },
                },
            },
        )
        branding.add_resource_dependency(primary_domain)
        health_check.node.add_dependency(branding)

        CfnOutput(self, "HostedLoginUrl", value=f"https://{AUTH_DOMAIN}")
        CfnOutput(self, "FailoverHealthCheckId", value=health_check.health_check_id)
