#!/usr/bin/env python3
import os

import aws_cdk as cdk

from cognito.cognito_stackuse1 import CognitoStackUse1
from cognito.cognito_stackuse2 import CognitoStackUse2
from cognito.cognito_stackusw2 import CognitoStackUsw2

app = cdk.App()

CognitoStackUse1(
    app, 'CognitoStackUse1',
    env = cdk.Environment(
        account = os.getenv('CDK_DEFAULT_ACCOUNT'),
        region = 'us-east-1'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    )
)

CognitoStackUse2(
    app, 'CognitoStackUse2',
    env = cdk.Environment(
        account = os.getenv('CDK_DEFAULT_ACCOUNT'),
        region = 'us-east-2'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    )
)

CognitoStackUsw2(
    app, 'CognitoStackUsw2',
    env = cdk.Environment(
        account = os.getenv('CDK_DEFAULT_ACCOUNT'),
        region = 'us-west-2'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    )
)

cdk.Tags.of(app).add('Alias','cognito')
cdk.Tags.of(app).add('GitHub','https://github.com/jblukach/cognito')
cdk.Tags.of(app).add('Org','lukach.io')

app.synth()