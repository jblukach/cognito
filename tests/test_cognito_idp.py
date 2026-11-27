import json
import os
import unittest

os.environ.setdefault(
    "JSII_RUNTIME_PACKAGE_CACHE_ROOT", os.path.expanduser("~/.jsii-package-cache")
)

from aws_cdk import (
    App,
    Environment,
    aws_route53 as route53,
    aws_route53_targets as route53_targets,
)
from aws_cdk.assertions import Template

from cognito.cognito_domain import CognitoDomainStack, CognitoReplicaSesStack
from cognito.cognito_idp import (
    CognitoCredentialsStack,
    CognitoIdpStack,
    CognitoManagedLoginStack,
    CognitoReplicaConfigurationStack,
    CognitoReplicaKeyStack,
    CognitoReplicaStack,
)


class CognitoClientTest(unittest.TestCase):
    def test_user_pool_requires_mfa_with_totp_and_verified_passkeys(self):
        app = App()
        stack = CognitoIdpStack(
            app,
            "TestIdp",
            ses_identity_arn="arn:aws:ses:us-east-1:123456789012:identity/auth.4n6ir.com",
            ses_configuration_set="test-configuration-set",
            env=Environment(account="123456789012", region="us-east-1"),
        )
        pool = Template.from_stack(stack).to_json()["Resources"]["UserPool"]["Properties"]
        self.assertEqual(
            set(pool["Policies"]["SignInPolicy"]["AllowedFirstAuthFactors"]),
            {"PASSWORD", "WEB_AUTHN"},
        )
        self.assertEqual(pool["MfaConfiguration"], "ON")
        self.assertEqual(pool["EnabledMfas"], ["SOFTWARE_TOKEN_MFA"])
        self.assertEqual(
            pool["WebAuthnFactorConfiguration"], "MULTI_FACTOR_WITH_USER_VERIFICATION"
        )
        self.assertEqual(pool["WebAuthnRelyingPartyID"], "auth.4n6ir.com")
        self.assertEqual(pool["WebAuthnUserVerification"], "required")

    def test_user_pool_has_no_public_app_client(self):
        app = App()
        stack = CognitoIdpStack(
            app,
            "TestIdp",
            ses_identity_arn="arn:aws:ses:us-east-1:123456789012:identity/auth.4n6ir.com",
            ses_configuration_set="test-configuration-set",
            env=Environment(account="123456789012", region="us-east-1"),
        )
        clients = Template.from_stack(stack).find_resources(
            "AWS::Cognito::UserPoolClient"
        )
        self.assertEqual(clients, {})

        resources = Template.from_stack(stack).to_json()["Resources"]
        tracking = resources["UserPoolSessionTracking"]
        self.assertEqual(tracking["Properties"]["UserSessionTracking"], "ENABLED")
        self.assertEqual(tracking["Properties"]["TokenSession"]["MaxPerUser"], 20)

    def test_verification_email_includes_code_and_safety_guidance(self):
        app = App()
        stack = CognitoIdpStack(
            app, "TestIdp",
            ses_identity_arn="arn:aws:ses:us-east-1:123456789012:identity/auth.4n6ir.com",
            ses_configuration_set="test-configuration-set",
            env=Environment(account="123456789012", region="us-east-1"),
        )
        pool = Template.from_stack(stack).to_json()["Resources"]["UserPool"]["Properties"]
        message = pool["VerificationMessageTemplate"]["EmailMessage"]
        self.assertIn("{####}", message)
        self.assertIn("Never share", message)

    def test_confirmation_role_can_use_pool_key_through_cognito(self):
        app = App()
        stack = CognitoIdpStack(
            app, "TestIdp",
            ses_identity_arn="arn:aws:ses:us-east-1:123456789012:identity/auth.4n6ir.com",
            ses_configuration_set="test-configuration-set",
            env=Environment(account="123456789012", region="us-east-1"),
        )
        resources = Template.from_stack(stack).to_json()["Resources"]
        role_id = next(
            name for name, resource in resources.items()
            if name.startswith("AssignDashboardBirthrightServiceRole")
            and resource["Type"] == "AWS::IAM::Role"
        )
        policy = next(
            resource["Properties"] for resource in resources.values()
            if resource["Type"] == "AWS::IAM::Policy"
            and {"Ref": role_id} in resource["Properties"]["Roles"]
        )
        statements = policy["PolicyDocument"]["Statement"]
        decrypt = next(s for s in statements if "kms:Decrypt" in s["Action"])
        self.assertEqual(
            set(decrypt["Action"]),
            {"kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKeyWithoutPlainText"},
        )
        self.assertEqual(decrypt["Resource"], {"Fn::GetAtt": ["UserPoolEncryptionKey", "Arn"]})
        self.assertEqual(
            decrypt["Condition"]["StringEquals"]["kms:ViaService"],
            {"Fn::Join": ["", ["cognito-idp.us-east-1.", {"Ref": "AWS::URLSuffix"}]]},
        )
        self.assertEqual(
            decrypt["Condition"]["StringLike"]["kms:EncryptionContext:aws:cognito-idp:userpool-arn"],
            {"Fn::Join": ["", ["arn:", {"Ref": "AWS::Partition"}, ":cognito-idp:us-east-1:123456789012:userpool/*"]]},
        )
        describe = next(s for s in statements if s["Action"] == "kms:DescribeKey")
        self.assertEqual(describe["Resource"], decrypt["Resource"])
        self.assertEqual(describe["Condition"]["StringEquals"], decrypt["Condition"]["StringEquals"])


class LoggingAndIssuerTest(unittest.TestCase):
    def test_log_destinations_and_replica_issuer(self):
        app = App()
        primary_env = Environment(account="123456789012", region="us-east-1")
        replica_env = Environment(account="123456789012", region="us-west-2")
        primary = CognitoIdpStack(
            app, "Primary",
            ses_identity_arn="arn:aws:ses:us-east-1:123456789012:identity/auth.4n6ir.com",
            ses_configuration_set="test-configuration-set",
            env=primary_env, cross_region_references=True,
        )
        replica_key = CognitoReplicaKeyStack(
            app, "ReplicaKey", primary_encryption_key=primary.encryption_key,
            env=replica_env, cross_region_references=True,
        )
        replica = CognitoReplicaStack(
            app, "Replica", primary_user_pool=primary.user_pool,
            replica_key_stack=replica_key, env=primary_env,
            cross_region_references=True,
        )
        replica_configuration = CognitoReplicaConfigurationStack(
            app, "ReplicaConfiguration", primary_user_pool=primary.user_pool,
            ses_identity_arn="arn:aws:ses:us-west-2:123456789012:identity/auth.4n6ir.com",
            ses_configuration_set="test-configuration-set",
            replica_key_stack=replica_key, replica_registration_stack=replica,
            env=replica_env, cross_region_references=True,
        )
        credentials = CognitoCredentialsStack(
            app, "Credentials", user_pool=primary.user_pool,
            replica_credentials_key=replica_configuration.credentials_key,
            env=primary_env, cross_region_references=True,
        )
        credential_template = Template.from_stack(credentials).to_json()
        credential_resources = credential_template["Resources"]
        clients = Template.from_stack(credentials).find_resources(
            "AWS::Cognito::UserPoolClient"
        )
        self.assertEqual(set(clients), {"EdgeAppClient"})
        edge = credential_resources["EdgeAppClient"]["Properties"]
        self.assertTrue(edge["GenerateSecret"])
        self.assertIn("ALLOW_USER_AUTH", edge["ExplicitAuthFlows"])
        self.assertNotIn("ALLOW_REFRESH_TOKEN_AUTH", edge["ExplicitAuthFlows"])
        self.assertEqual(edge["RefreshTokenRotation"]["Feature"], "ENABLED")
        self.assertEqual(
            edge["CallbackURLs"],
            ["https://4n6ir.com/callback", "https://www.4n6ir.com/callback"],
        )
        self.assertEqual(edge["LogoutURLs"], ["https://4n6ir.com/", "https://www.4n6ir.com/"])
        self.assertEqual(edge["RefreshTokenValidity"], 1)
        self.assertEqual(edge["AccessTokenValidity"], 15)
        self.assertEqual(edge["IdTokenValidity"], 15)
        self.assertEqual(
            credential_resources["EdgeClientSession"]["Properties"]["SSOSession"]["MaxValidityMinutes"],
            15,
        )
        secret = next(
            resource for resource in credential_resources.values()
            if resource["Type"] == "AWS::SecretsManager::Secret"
        )["Properties"]
        self.assertEqual(secret["Name"], "credentials")
        self.assertEqual(secret["ReplicaRegions"][0]["Region"], "us-west-2")
        secret_string = json.dumps(secret["SecretString"])
        self.assertIn("CLIENT_ID", secret_string)
        self.assertIn("CLIENT_SECRET", secret_string)
        self.assertIn('"Fn::GetAtt": ["EdgeAppClient", "ClientSecret"]', secret_string)
        self.assertNotIn("ClientSecret", json.dumps(credential_template.get("Outputs", {})))
        for stack, region in ((credentials, "us-east-1"), (replica_configuration, "us-west-2")):
            keys = Template.from_stack(stack).find_resources("AWS::KMS::Key")
            key = next(value for name, value in keys.items() if name.startswith("CredentialsKey"))
            policy = json.dumps(key["Properties"]["KeyPolicy"])
            self.assertIn(f"secretsmanager.{region}.", policy)
            self.assertIn(":secret:credentials-*", policy)
            self.assertIn("kms:Decrypt", policy)
            self.assertIn("accountdomains", policy)
        policies = Template.from_stack(credentials).find_resources("AWS::SecretsManager::ResourcePolicy")
        self.assertEqual(len(policies), 1)
        self.assertIn("secretsmanager:GetSecretValue", json.dumps(policies))
        self.assertIn("accountdomains", json.dumps(policies))
        for stack, resource_id, regions in (
            (primary, "UserPoolEncryptionKey", ("us-east-1", "us-west-2")),
            (replica_key, "UserPoolEncryptionKeyReplica", ("us-east-1", "us-west-2")),
        ):
            key = Template.from_stack(stack).to_json()["Resources"][resource_id]
            statements = {
                statement["Sid"]: statement
                for statement in key["Properties"]["KeyPolicy"]["Statement"]
            }
            for region in regions:
                region_suffix = region.replace("-", "")
                for prefix in ("AllowCognitoUserPoolEncryption", "AllowCognitoDescribeKey"):
                    statement = statements[prefix + region_suffix]
                    self.assertEqual(
                        set(statement["Principal"]["Service"]),
                        {"cognito-idp.amazonaws.com", "identitystore.amazonaws.com"},
                    )
                    self.assertIn("aws:SourceAccount", statement["Condition"]["StringEquals"])
                    self.assertIn("aws:SourceArn", statement["Condition"]["ArnLike"])
                contexts = statements["AllowCognitoUserPoolEncryption" + region_suffix][
                    "Condition"
                ]["StringLike"]["kms:EncryptionContext:aws:cognito-idp:userpool-arn"]
                self.assertIn("cognito-idp:us-east-1:123456789012:userpool/*", json.dumps(contexts))
                self.assertIn("cognito-idp:us-west-2:123456789012:userpool/*", json.dumps(contexts))

        for stack, region in (
            (primary, "us-east-1"),
            (replica_configuration, "us-west-2"),
        ):
            template = Template.from_stack(stack).to_json()
            resources = template["Resources"]
            log_group_id = next(
                name for name, resource in resources.items()
                if resource["Type"] == "AWS::Logs::LogGroup"
            )
            delivery = next(
                resource for resource in resources.values()
                if resource["Type"] == "AWS::Cognito::LogDeliveryConfiguration"
            )
            expected_arn = {
                "Fn::Join": [
                    "",
                    [
                        "arn:",
                        {"Ref": "AWS::Partition"},
                        f":logs:{region}:123456789012:log-group:",
                        {"Ref": log_group_id},
                    ],
                ]
            }
            configs = delivery["Properties"]["LogConfigurations"]
            self.assertEqual(
                {config["EventSource"] for config in configs},
                {"userAuthEvents", "userNotification"},
            )
            for config in configs:
                self.assertEqual(
                    config["CloudWatchLogsConfiguration"]["LogGroupArn"],
                    expected_arn,
                )

        primary_email = Template.from_stack(primary).to_json()["Resources"]["UserPool"][
            "Properties"
        ]["EmailConfiguration"]
        replica_email = Template.from_stack(replica_configuration).to_json()["Resources"][
            "UserPoolReplicaConfiguration"
        ]["Properties"]["EmailConfiguration"]
        for config in (primary_email, replica_email):
            self.assertEqual(config["ConfigurationSet"], "test-configuration-set")
            self.assertEqual(config["ReplyToEmailAddress"], "hello@4n6ir.com")
            self.assertEqual(config["From"], "no-reply@auth.4n6ir.com")

        issuer = Template.from_stack(replica_configuration).to_json()["Outputs"][
            "ReplicaUpdatedIssuer"
        ]["Value"]
        self.assertIn(
            "https://issuer-cognito-idp.us-east-1.amazonaws.com/", json.dumps(issuer)
        )
        self.assertNotIn("us-west-2", json.dumps(issuer))


class ManagedLoginFailoverTest(unittest.TestCase):
    def test_health_check_uses_primary_prefix_login(self):
        app = App()
        primary_env = Environment(account="123456789012", region="us-east-1")
        replica_env = Environment(account="123456789012", region="us-west-2")
        zone = route53.HostedZone.from_hosted_zone_attributes(
            app, "AuthZone", hosted_zone_id="ZEXAMPLE", zone_name="auth.4n6ir.com"
        )
        idp = CognitoIdpStack(
            app, "TestIdp",
            ses_identity_arn="arn:aws:ses:us-east-1:123456789012:identity/auth.4n6ir.com",
            ses_configuration_set="test-configuration-set",
            env=primary_env,
            cross_region_references=True,
        )
        replica_key = CognitoReplicaKeyStack(
            app, "TestReplicaKey",
            primary_encryption_key=idp.encryption_key, env=replica_env,
            cross_region_references=True,
        )
        replica = CognitoReplicaStack(
            app, "TestReplica", primary_user_pool=idp.user_pool,
            replica_key_stack=replica_key, env=primary_env,
            cross_region_references=True,
        )
        replica_configuration = CognitoReplicaConfigurationStack(
            app, "TestReplicaConfiguration", primary_user_pool=idp.user_pool,
            ses_identity_arn="arn:aws:ses:us-west-2:123456789012:identity/auth.4n6ir.com",
            ses_configuration_set="test-configuration-set",
            replica_key_stack=replica_key, replica_registration_stack=replica,
            env=replica_env, cross_region_references=True,
        )
        credentials = CognitoCredentialsStack(
            app, "TestCredentials", user_pool=idp.user_pool,
            replica_credentials_key=replica_configuration.credentials_key,
            env=primary_env, cross_region_references=True,
        )
        stack = CognitoManagedLoginStack(
            app,
            "TestLogin",
            hosted_zone=zone,
            user_pool=idp.user_pool,
            edge_client=credentials.edge_client,
            replica_configuration_stack=replica_configuration,
            env=primary_env,
            cross_region_references=True,
        )
        template = Template.from_stack(stack).to_json()
        resources = template["Resources"]
        prefix = resources["PrimaryHealthCheckDomain"]
        self.assertEqual(prefix["Properties"]["ManagedLoginVersion"], 2)
        self.assertNotIn("Routing", prefix["Properties"])
        self.assertNotIn("CustomDomainConfig", prefix["Properties"])
        health_checks = {
            key: value
            for key, value in resources.items()
            if value["Type"] == "AWS::Route53::HealthCheck"
        }
        self.assertEqual(len(health_checks), 1)
        health_id, health_check = next(iter(health_checks.items()))
        config = health_check["Properties"]["HealthCheckConfig"]
        self.assertEqual(config["Type"], "HTTPS")
        self.assertEqual(config["RequestInterval"], 30)
        self.assertEqual(config["FailureThreshold"], 3)
        self.assertTrue(config["EnableSNI"])
        self.assertEqual(
            template["Outputs"]["FailoverHealthCheckId"]["Value"],
            {"Ref": health_id},
        )
        self.assertIn(
            "PrimaryHealthCheckDomain",
            json.dumps(config["FullyQualifiedDomainName"]),
        )
        self.assertIn(
            ".amazoncognito.com", json.dumps(config["FullyQualifiedDomainName"])
        )
        self.assertIn(
            "/login?response_type=code&client_id=", json.dumps(config["ResourcePath"])
        )
        self.assertIn("EdgeAppClient", json.dumps(config["ResourcePath"]))
        self.assertIn(
            "redirect_uri=https%3A%2F%2F4n6ir.com%2Fcallback",
            json.dumps(config["ResourcePath"]),
        )
        self.assertIn("EdgeManagedLoginBranding", health_check["DependsOn"])
        self.assertEqual(
            resources["ManagedLoginDomain"]["Properties"]["Routing"]["Failover"],
            {
                "PrimaryRoute53HealthCheckId": {"Ref": health_id},
                "SecondaryRegion": "us-west-2",
            },
        )
        self.assertEqual(
            resources["ManagedLoginDomain"]["Properties"]["CustomDomainConfig"]["SecurityPolicy"],
            "TLS_V1_3_2025",
        )
        branding = resources["EdgeManagedLoginBranding"]
        self.assertIn("EdgeAppClient", json.dumps(branding["Properties"]["ClientId"]))
        self.assertEqual(
            {
                key
                for key, resource in resources.items()
                if resource["Type"] == "AWS::Cognito::ManagedLoginBranding"
            },
            {"EdgeManagedLoginBranding"},
        )
        components = branding["Properties"]["Settings"][
            "components"
        ]
        self.assertFalse(components["pageBackground"]["image"]["enabled"])
        self.assertEqual(components["pageBackground"]["lightMode"]["color"], "bdefcaff")
        self.assertEqual(
            components["pageHeader"]["lightMode"]["background"]["color"], "ffffffff"
        )
        self.assertEqual(
            components["primaryButton"]["lightMode"],
            {
                "active": {"backgroundColor": "033160ff", "textColor": "ffffffff"},
                "defaults": {"backgroundColor": "0972d3ff", "textColor": "ffffffff"},
                "hover": {"backgroundColor": "033160ff", "textColor": "ffffffff"},
            },
        )
        self.assertEqual(
            branding["Properties"]["Settings"]["componentClasses"]["focusState"]["lightMode"],
            {"borderColor": "0972d3ff"},
        )
        self.assertEqual(components["form"]["lightMode"]["borderColor"], "bdefcaff")
        for record_type in ("A", "AAAA"):
            record = resources[f"ManagedLogin{record_type}Record"]["Properties"]
            self.assertEqual(record["Type"], record_type)
            self.assertEqual(
                record["AliasTarget"],
                {
                    "DNSName": {"Fn::GetAtt": ["ManagedLoginDomain", "CloudFrontDistribution"]},
                    "HostedZoneId": stack.resolve(
                        route53_targets.CloudFrontTarget.get_hosted_zone_id(stack)
                    ),
                    "EvaluateTargetHealth": False,
                },
            )


class SesDomainTest(unittest.TestCase):
    def test_domain_stack_contains_both_regions_dkim_records(self):
        app = App()
        replica = CognitoReplicaSesStack(
            app, "ReplicaSes",
            env=Environment(account="123456789012", region="us-west-2"),
            cross_region_references=True,
        )
        domain = CognitoDomainStack(
            app, "Domain", replica_identity=replica.identity,
            env=Environment(account="123456789012", region="us-east-1"),
            cross_region_references=True,
        )
        idp = CognitoIdpStack(
            app, "Idp", ses_identity_arn=domain.primary_identity_arn,
            ses_configuration_set=domain.configuration_set_name,
            env=Environment(account="123456789012", region="us-east-1"),
            cross_region_references=True,
        )
        domain_resources = Template.from_stack(domain).to_json()["Resources"]
        replica_resources = Template.from_stack(replica).to_json()["Resources"]
        self.assertEqual(
            domain_resources["UserPoolSesIdentity"]["Properties"]["EmailIdentity"],
            "auth.4n6ir.com",
        )
        self.assertEqual(
            replica_resources["UserPoolSesIdentity"]["Properties"]["EmailIdentity"],
            "auth.4n6ir.com",
        )
        self.assertIn(replica, domain.dependencies)
        for region in ("Primary", "Replica"):
            for index in range(1, 4):
                record = domain_resources[f"Ses{region}DkimRecord{index}"]["Properties"]
                self.assertEqual(record["Type"], "CNAME")
                self.assertEqual(record["HostedZoneId"], {"Ref": "hostzone2271E7B7"})
                self.assertIn(f"DkimDNSTokenName{index}", json.dumps(record["Name"]))
                self.assertIn(
                    f"DkimDNSTokenValue{index}",
                    json.dumps(record["ResourceRecords"]),
                )
        idp_resources = Template.from_stack(idp).to_json()["Resources"]
        self.assertIn(domain, idp.dependencies)
        self.assertFalse(any(
            resource["Type"] == "AWS::SES::EmailIdentity"
            for resource in idp_resources.values()
        ))
        self.assertIn(
            "UserPoolSesIdentity",
            json.dumps(idp_resources["UserPool"]["Properties"]["EmailConfiguration"]),
        )

    def test_ses_feedback_is_published_to_reply_address_in_both_regions(self):
        app = App()
        replica = CognitoReplicaSesStack(
            app, "ReplicaSes",
            env=Environment(account="123456789012", region="us-west-2"),
            cross_region_references=True,
        )
        domain = CognitoDomainStack(
            app, "Domain", replica_identity=replica.identity,
            env=Environment(account="123456789012", region="us-east-1"),
            cross_region_references=True,
        )
        for stack in (domain, replica):
            resources = Template.from_stack(stack).to_json()["Resources"]
            identity = resources["UserPoolSesIdentity"]
            self.assertEqual(
                identity["Properties"]["ConfigurationSetAttributes"]["ConfigurationSetName"],
                {"Ref": "SesConfigurationSet"},
            )
            self.assertFalse(
                identity["Properties"]["FeedbackAttributes"]["EmailForwardingEnabled"]
            )
            self.assertIn("SesFeedbackDestination", identity["DependsOn"])
            destination = resources["SesFeedbackDestination"]
            self.assertEqual(
                destination["Properties"]["ConfigurationSetName"],
                {"Ref": "SesConfigurationSet"},
            )
            event = destination["Properties"]["EventDestination"]
            self.assertTrue(event["Enabled"])
            self.assertEqual(event["MatchingEventTypes"], ["BOUNCE", "COMPLAINT"])
            subscriptions = [
                resource["Properties"] for resource in resources.values()
                if resource["Type"] == "AWS::SNS::Subscription"
            ]
            self.assertEqual(len(subscriptions), 1)
            self.assertEqual(subscriptions[0]["Protocol"], "email")
            self.assertEqual(subscriptions[0]["Endpoint"], "hello@4n6ir.com")
            self.assertEqual(subscriptions[0]["TopicArn"], event["SnsDestination"]["TopicARN"])
            self.assertTrue(any(
                resource["Type"] == "AWS::SNS::TopicPolicy"
                and "ses.amazonaws.com" in json.dumps(resource["Properties"])
                and "configuration-set/" in json.dumps(resource["Properties"])
                for resource in resources.values()
            ))


if __name__ == "__main__":
    unittest.main()
