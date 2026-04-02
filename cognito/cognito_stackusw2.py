import datetime

from aws_cdk import (
    Duration,
    RemovalPolicy,
    SecretValue,
    Stack,
    aws_certificatemanager as _acm,
    aws_cognito as _cognito,
    aws_iam as _iam,
    aws_lambda as _lambda,
    aws_logs as _logs,
    aws_route53 as _route53,
    aws_route53_targets as _r53targets,
    aws_s3 as _s3,
    aws_ssm as _ssm
)

from constructs import Construct

class CognitoStackUsw2(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        account = Stack.of(self).account
        region = Stack.of(self).region

        year = datetime.datetime.now().strftime('%Y')
        month = datetime.datetime.now().strftime('%m')
        day = datetime.datetime.now().strftime('%d')

    ### S3 BUCKETS ###

        bucket = _s3.Bucket.from_bucket_name(
            self, 'bucket',
            bucket_name = 'packages-usw2-lukach-io'
        )

    ### LAMBDA LAYER ###

        requests = _lambda.LayerVersion(
            self, 'requests',
            layer_version_name = 'requests',
            description = str(year)+'-'+str(month)+'-'+str(day)+' deployment',
            code = _lambda.Code.from_bucket(
                bucket = bucket,
                key = 'requests.zip'
            ),
            compatible_architectures = [
                _lambda.Architecture.ARM_64
            ],
            compatible_runtimes = [
                _lambda.Runtime.PYTHON_3_13
            ],
            removal_policy = RemovalPolicy.DESTROY
        )

    ### HOSTZONE ###

        hostzone = _route53.HostedZone.from_lookup(
            self, 'hostzone',
            domain_name = 'hello-usw2.lukach.io'
        )

    ### PARAMETER ###

        apigateway = _ssm.StringParameter.from_string_parameter_attributes(
            self, 'apigateway',
            parameter_name = '/account/api'
        )

    ### ACM CERTIFICATE ###

        acm = _acm.Certificate.from_certificate_arn(
            self, 'acm',
            'arn:aws:acm:us-east-1:'+account+':certificate/8cf8eca6-a4d2-4b92-a304-cd218f88df55'
        )

    ### COGNITO USER POOL ###

        userpool = _cognito.UserPool(
            self, 'userpool',
            user_pool_name = 'lunker',
            deletion_protection = True,
            removal_policy = RemovalPolicy.RETAIN,
            feature_plan = _cognito.FeaturePlan.PLUS,
            standard_threat_protection_mode = _cognito.StandardThreatProtectionMode.AUDIT_ONLY,
            custom_threat_protection_mode = _cognito.CustomThreatProtectionMode.AUDIT_ONLY,
            self_sign_up_enabled = False,
            sign_in_aliases = _cognito.SignInAliases(
                email = True
            ),
            email = _cognito.UserPoolEmail.with_ses(
                from_email = 'hello@lukach.io'
            ),
            sign_in_case_sensitive = False,
            sign_in_policy = _cognito.SignInPolicy(
                allowed_first_auth_factors = _cognito.AllowedFirstAuthFactors(
                    password = True,
                    email_otp = True,
                    passkey = True
                )
            ),
            auto_verify = _cognito.AutoVerifiedAttrs(
                email = False,
                phone = False
            ),
            account_recovery = _cognito.AccountRecovery.NONE,
            device_tracking = _cognito.DeviceTracking(
                challenge_required_on_new_device = True,
                device_only_remembered_on_user_prompt = False
            ),
            passkey_user_verification = _cognito.PasskeyUserVerification.PREFERRED,
            mfa = _cognito.Mfa.OFF
        )

    ### COGNITO APP CLIENT ###

        appclient = userpool.add_client(
            'appclient',
            user_pool_client_name = 'lunker',
            prevent_user_existence_errors = True,
            auth_flows = _cognito.AuthFlow(
                user = True,
                user_srp = True
            ),
            o_auth = _cognito.OAuthSettings(
                default_redirect_uri = 'https://usw2.api.lukach.io/auth',
                callback_urls = [
                    'https://usw2.api.lukach.io/auth'
                ],
                flows = _cognito.OAuthFlows(
                    authorization_code_grant = True
                ),
                scopes = [
                    _cognito.OAuthScope.OPENID
                ]
            ),
            generate_secret = True
        )

    #### COGNITO BRANDING ###

        branding = _cognito.CfnManagedLoginBranding(
            self, 'branding',
            user_pool_id = userpool.user_pool_id,
            client_id = appclient.user_pool_client_id,
            use_cognito_provided_values = True
        )

    ### COGNITO DOMAIN ###

        domain = userpool.add_domain(
            'domain',
            custom_domain = _cognito.CustomDomainOptions(
                domain_name = 'hello-usw2.lukach.io',
                certificate = acm
            ),
            managed_login_version = _cognito.ManagedLoginVersion.NEWER_MANAGED_LOGIN
        )

    ### COGNITO DNS ###

        cognitofour = _route53.ARecord(
            self, 'cognitofour',
            zone = hostzone,
            record_name = 'hello-usw2.lukach.io',
            target = _route53.RecordTarget.from_alias(
                _r53targets.UserPoolDomainTarget(domain)
            )
        )

        cognitofsix = _route53.AaaaRecord(
            self, 'cognitofsix',
            zone = hostzone,
            record_name = 'hello-usw2.lukach.io',
            target = _route53.RecordTarget.from_alias(
                _r53targets.UserPoolDomainTarget(domain)
            )
        )

    ### COGNITO LOGS ###

        authenticationlogs = _logs.LogGroup(
            self, 'authenticationlogs',
            log_group_name = '/aws/cognito/lunker/authentication',
            retention = _logs.RetentionDays.THIRTEEN_MONTHS,
            removal_policy = RemovalPolicy.DESTROY
        )

        authenticationlogsdelivery = _cognito.CfnLogDeliveryConfiguration(
            self, 'authenticationlogsdelivery',
            user_pool_id = userpool.user_pool_id,
            log_configurations = [
                _cognito.CfnLogDeliveryConfiguration.LogConfigurationProperty(
                    cloud_watch_logs_configuration = _cognito.CfnLogDeliveryConfiguration.CloudWatchLogsConfigurationProperty(
                        log_group_arn = 'arn:aws:logs:'+region+':'+account+':log-group:/aws/cognito/lunker/authentication'
                    ),
                    event_source = 'userAuthEvents',
                    log_level = 'INFO'
                )
            ]
        )

    ### IAM ROLE ###

        role = _iam.Role(
            self, 'role',
            assumed_by = _iam.ServicePrincipal(
                'lambda.amazonaws.com'
            )
        )

        role.add_managed_policy(
            _iam.ManagedPolicy.from_aws_managed_policy_name(
                'service-role/AWSLambdaBasicExecutionRole'
            )
        )

        role.add_to_policy(
            _iam.PolicyStatement(
                actions = [
                    'apigateway:GET'
                ],
                resources = [
                    '*'
                ]
            )
        )

        composite = _iam.CompositePrincipal(
            _iam.AccountPrincipal(apigateway.string_value),
            _iam.ServicePrincipal('apigateway.amazonaws.com')
        )

    ### AUTH LAMBDA FUNCTION ###

        auth = _lambda.Function(
            self, 'auth',
            function_name = 'auth',
            runtime = _lambda.Runtime.PYTHON_3_13,
            architecture = _lambda.Architecture.ARM_64,
            code = _lambda.Code.from_asset('auth'),
            handler = 'authusw2.handler',
            environment = dict(
                CLIENT_ID = appclient.user_pool_client_id,
                CLIENT_SECRET = SecretValue.unsafe_unwrap(appclient.user_pool_client_secret)
            ),
            timeout = Duration.seconds(7),
            memory_size = 128,
            role = role,
            layers = [
                requests
            ]
        )

        auth.grant_invoke_composite_principal(composite)

        authlogs = _logs.LogGroup(
            self, 'authlogs',
            log_group_name = '/aws/lambda/'+auth.function_name,
            retention = _logs.RetentionDays.THIRTEEN_MONTHS,
            removal_policy = RemovalPolicy.DESTROY
        )

    ### ROOT LAMBDA FUNCTION ###

        root = _lambda.Function(
            self, 'root',
            function_name = 'root',
            runtime = _lambda.Runtime.PYTHON_3_13,
            architecture = _lambda.Architecture.ARM_64,
            code = _lambda.Code.from_asset('root'),
            handler = 'rootusw2.handler',
            environment = dict(
                CLIENT_ID = appclient.user_pool_client_id
            ),
            timeout = Duration.seconds(7),
            memory_size = 128,
            role = role
        )

        root.grant_invoke_composite_principal(composite)

        rootlogs = _logs.LogGroup(
            self, 'rootlogs',
            log_group_name = '/aws/lambda/'+root.function_name,
            retention = _logs.RetentionDays.THIRTEEN_MONTHS,
            removal_policy = RemovalPolicy.DESTROY
        )
