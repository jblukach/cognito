from aws_cdk import (
    RemovalPolicy,
    Stack,
    aws_iam as _iam,
    aws_logs as _logs,
    aws_route53 as _route53
)

from constructs import Construct

class CognitoDomainStack(Stack):

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
            resource_policy_name = 'Route53LogsPolicyAuth4n6irCom'
        )

        logs = _logs.LogGroup(
            self, 'logs',
            log_group_name = '/aws/route53/auth4n6ircom',
            retention = _logs.RetentionDays.THIRTEEN_MONTHS,
            removal_policy = RemovalPolicy.DESTROY
        )

        hostzone = _route53.PublicHostedZone(
            self, 'hostzone', 
            zone_name = 'auth.4n6ir.com',
            comment = 'auth.4n6ir.com',
            accelerated_recovery_enabled = True,
            query_logs_log_group_arn = logs.log_group_arn
        )
