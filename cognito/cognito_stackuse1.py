from aws_cdk import (
    RemovalPolicy,
    Stack,
    aws_certificatemanager as _acm,
    aws_cognito as _cognito,
    aws_iam as _iam,
    aws_logs as _logs,
    aws_route53 as _route53,
    aws_ssm as _ssm
)

from constructs import Construct

class CognitoStackUse1(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        account = Stack.of(self).account
        region = Stack.of(self).region

    ### HOSTZONE ###

        policy_statement = _iam.PolicyStatement(
            principals = [
                _iam.ServicePrincipal('route53.amazonaws.com')
            ],
            actions = [
                'logs:CreateLogStream',
                'logs:PutLogEvents'
            ],
            resources=[
                'arn:aws:logs:'+region+':'+account+':log-group:*'
            ]
        )

        resourcepolicy = _logs.ResourcePolicy(
            self, 'resourcepolicy',
            policy_statements = [
                policy_statement
            ],
            resource_policy_name = 'Route53LogsPolicyHelloLukachIo'
        )

        logs = _logs.LogGroup(
            self, 'logs',
            log_group_name = '/aws/route53/hellolukachio',
            retention = _logs.RetentionDays.THIRTEEN_MONTHS,
            removal_policy = RemovalPolicy.DESTROY
        )

        hostzone = _route53.PublicHostedZone(
            self, 'hostzone', 
            zone_name = 'hello.lukach.io',
            comment = 'hello.lukach.io',
            query_logs_log_group_arn = logs.log_group_arn
        )

    ### PARAMETER ###

        parameter = _ssm.StringParameter(
            self, 'parameter',
            description = 'hello.lukach.io',
            parameter_name = '/route53/hellolukachio',
            string_value = hostzone.hosted_zone_id,
            tier = _ssm.ParameterTier.STANDARD
        )

    ### ACM CERTIFICATE ###

        acm = _acm.Certificate(
            self, 'acm',
            domain_name = 'hello.lukach.io',
            subject_alternative_names = [
                'use1.hello.lukach.io'
            ],
            validation = _acm.CertificateValidation.from_dns(hostzone)
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
