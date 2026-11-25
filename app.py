#!/usr/bin/env python3
import os

# Keep the jsii cache outside potentially group-writable XDG cache directories.
os.environ.setdefault('JSII_RUNTIME_PACKAGE_CACHE_ROOT', os.path.expanduser('~/.jsii-package-cache'))

import aws_cdk as cdk

from cognito.cognito_stack import CognitoStack

app = cdk.App()

CognitoStack(app, "CognitoStack",
    env = cdk.Environment(
        account = os.getenv('CDK_DEFAULT_ACCOUNT'),
        region = 'us-east-2'
    ),
    synthesizer = cdk.DefaultStackSynthesizer(
        qualifier = 'lukach'
    )
)

cdk.Tags.of(app).add('Alias','cognito')
cdk.Tags.of(app).add('Domain','lukach.io')
cdk.Tags.of(app).add('GitHub','https://github.com/jblukach/cognito')

app.synth()