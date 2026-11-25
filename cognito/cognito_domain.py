from aws_cdk import (
    RemovalPolicy,
    Stack,
    aws_iam as _iam,
    aws_logs as _logs,
    aws_route53 as _route53,
    aws_ses as _ses,
    aws_sns as _sns,
    aws_sns_subscriptions as _sns_subscriptions,
)

from constructs import Construct

AUTH_DOMAIN = "auth.4n6ir.com"
EMAIL_REPLY_TO_ADDRESS = "hello@4n6ir.com"


def _create_ses_identity(scope: Stack) -> tuple[_ses.CfnEmailIdentity, str]:
    configuration_set = _ses.CfnConfigurationSet(scope, "SesConfigurationSet")
    topic = _sns.Topic(scope, "SesFeedbackTopic")
    topic.add_subscription(_sns_subscriptions.EmailSubscription(EMAIL_REPLY_TO_ADDRESS))
    topic.add_to_resource_policy(
        _iam.PolicyStatement(
            principals=[_iam.ServicePrincipal("ses.amazonaws.com")],
            actions=["sns:Publish"],
            resources=[topic.topic_arn],
            conditions={
                "StringEquals": {
                    "aws:SourceAccount": scope.account,
                    "aws:SourceArn": scope.format_arn(
                        service="ses",
                        resource=f"configuration-set/{configuration_set.ref}",
                    ),
                }
            },
        )
    )
    destination = _ses.CfnConfigurationSetEventDestination(
        scope,
        "SesFeedbackDestination",
        configuration_set_name=configuration_set.ref,
        event_destination=_ses.CfnConfigurationSetEventDestination.EventDestinationProperty(
            name="Feedback",
            enabled=True,
            matching_event_types=["BOUNCE", "COMPLAINT"],
            sns_destination=_ses.CfnConfigurationSetEventDestination.SnsDestinationProperty(
                topic_arn=topic.topic_arn,
            ),
        ),
    )
    destination.node.add_dependency(topic.node.find_child("Policy"))
    identity = _ses.CfnEmailIdentity(
        scope,
        "UserPoolSesIdentity",
        email_identity=AUTH_DOMAIN,
        dkim_attributes=_ses.CfnEmailIdentity.DkimAttributesProperty(
            signing_enabled=True
        ),
        configuration_set_attributes=_ses.CfnEmailIdentity.ConfigurationSetAttributesProperty(
            configuration_set_name=configuration_set.ref
        ),
        feedback_attributes=_ses.CfnEmailIdentity.FeedbackAttributesProperty(
            email_forwarding_enabled=False
        ),
    )
    identity.add_resource_dependency(destination)
    return identity, configuration_set.ref


class CognitoReplicaSesStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.identity, self.configuration_set_name = _create_ses_identity(self)
        self.identity_arn = self.format_arn(
            service="ses", resource=f"identity/{self.identity.ref}"
        )


class CognitoDomainStack(Stack):

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        replica_identity: _ses.CfnEmailIdentity,
        **kwargs,
    ) -> None:
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
            resource_policy_name = 'Route53LogsPolicyAuth4n6irCom'
        )

        logs = _logs.LogGroup(
            self, 'logs',
            log_group_name = '/aws/route53/auth4n6ircom',
            retention = _logs.RetentionDays.THIRTEEN_MONTHS,
            removal_policy = RemovalPolicy.DESTROY
        )

        self.hostzone = _route53.PublicHostedZone(
            self, 'hostzone', 
            zone_name = AUTH_DOMAIN,
            comment = AUTH_DOMAIN,
            accelerated_recovery_enabled = True,
            query_logs_log_group_arn = logs.log_group_arn
        )

        primary_identity, self.configuration_set_name = _create_ses_identity(self)
        self.primary_identity_arn = self.format_arn(
            service="ses", resource=f"identity/{primary_identity.ref}"
        )
        for region, identity in (
            ("Primary", primary_identity),
            ("Replica", replica_identity),
        ):
            for index in range(1, 4):
                _route53.CfnRecordSet(
                    self,
                    f"Ses{region}DkimRecord{index}",
                    hosted_zone_id=self.hostzone.hosted_zone_id,
                    name=getattr(identity, f"attr_dkim_dns_token_name{index}"),
                    type="CNAME",
                    ttl="300",
                    resource_records=[
                        getattr(identity, f"attr_dkim_dns_token_value{index}")
                    ],
                )
