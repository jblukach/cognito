#!/usr/bin/env python3
import os

# Keep the jsii cache outside potentially group-writable XDG cache directories.
os.environ.setdefault('JSII_RUNTIME_PACKAGE_CACHE_ROOT', os.path.expanduser('~/.jsii-package-cache'))

import aws_cdk as cdk

from cognito.cognito_stack import CognitoStack
from cognito.cognito_domain import CognitoDomainStack, CognitoReplicaSesStack
from cognito.cognito_idp import (
    CognitoCredentialsStack,
    CognitoIdpStack,
    CognitoManagedLoginStack,
    CognitoReplicaConfigurationStack,
    CognitoReplicaKeyStack,
    CognitoReplicaStack,
)

app = cdk.App()

account = os.getenv('CDK_DEFAULT_ACCOUNT')

CognitoStack(app, "CognitoStack",
    env = cdk.Environment(
        account = account,
        region = 'us-east-2'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    )
)

replica_ses_stack = CognitoReplicaSesStack(app, "CognitoReplicaSesStack",
    env = cdk.Environment(
        account = account,
        region = 'us-west-2'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    ),
    cross_region_references = True
)

domain_stack = CognitoDomainStack(app, "CognitoDomainStack",
    replica_identity = replica_ses_stack.identity,
    env = cdk.Environment(
        account = account,
        region = 'us-east-1'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    ),
    cross_region_references = True
)

idp_stack = CognitoIdpStack(app, "CognitoIdpStack",
    ses_identity_arn = domain_stack.primary_identity_arn,
    ses_configuration_set = domain_stack.configuration_set_name,
    env = cdk.Environment(
        account = account,
        region = 'us-east-1'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    ),
    cross_region_references = True
)

replica_key_stack = CognitoReplicaKeyStack(app, "CognitoReplicaKeyStack",
    primary_encryption_key = idp_stack.encryption_key,
    env = cdk.Environment(
        account = account,
        region = 'us-west-2'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    ),
    cross_region_references = True
)

replica_stack = CognitoReplicaStack(app, "CognitoReplicaStack",
    primary_user_pool = idp_stack.user_pool,
    replica_key_stack = replica_key_stack,
    env = cdk.Environment(
        account = account,
        region = 'us-east-1'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    ),
    cross_region_references = True
)

replica_configuration_stack = CognitoReplicaConfigurationStack(
    app, "CognitoReplicaConfigurationStack",
    primary_user_pool = idp_stack.user_pool,
    ses_identity_arn = replica_ses_stack.identity_arn,
    ses_configuration_set = replica_ses_stack.configuration_set_name,
    replica_key_stack = replica_key_stack,
    replica_registration_stack = replica_stack,
    env = cdk.Environment(
        account = account,
        region = 'us-west-2'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    ),
    cross_region_references = True
)

credentials_stack = CognitoCredentialsStack(app, "CognitoCredentialsStack",
    user_pool = idp_stack.user_pool,
    replica_credentials_key = replica_configuration_stack.credentials_key,
    env = cdk.Environment(
        account = account,
        region = 'us-east-1'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    ),
    cross_region_references = True
)

CognitoManagedLoginStack(app, "CognitoManagedLoginStack",
    hosted_zone = domain_stack.hostzone,
    user_pool = idp_stack.user_pool,
    edge_client = credentials_stack.edge_client,
    replica_configuration_stack = replica_configuration_stack,
    env = cdk.Environment(
        account = account,
        region = 'us-east-1'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    ),
    cross_region_references = True
)

cdk.Tags.of(app).add('Alias','cognito')
cdk.Tags.of(app).add('Domain','4n6ir.com')
cdk.Tags.of(app).add('GitHub','https://github.com/jblukach/cognito')

app.synth()