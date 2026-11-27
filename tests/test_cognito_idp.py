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
from cognito.cognito_stack import CognitoStack
from cognito.cognito_idp import (
    CognitoCredentialsStack,
    CognitoIdpStack,
    CognitoManagedLoginStack,
    CognitoReplicaConfigurationStack,
    CognitoReplicaCredentialsParametersStack,
    CognitoReplicaKeyStack,
    CognitoReplicaStack,
)


class DeploymentRoleTest(unittest.TestCase):
    def test_risk_reads_can_decrypt_only_through_regional_cognito(self):
        stack = CognitoStack(
            App(), "Deployment", env=Environment(account="123456789012", region="us-east-2")
        )
        policies = Template.from_stack(stack).find_resources("AWS::IAM::Policy")
        statements = [
            statement
            for policy in policies.values()
            for statement in policy["Properties"]["PolicyDocument"]["Statement"]
            if statement["Action"] == "kms:Decrypt"
        ]
        self.assertEqual(len(statements), 2)
        for statement, region in zip(statements, ("us-east-1", "us-west-2")):
            self.assertIn(f":kms:{region}:123456789012:key/mrk-*", json.dumps(statement["Resource"]))
            self.assertIn(
                f"cognito-idp.{region}.",
                json.dumps(statement["Condition"]["StringEquals"]["kms:ViaService"]),
            )
            context = statement["Condition"]["StringLike"][
                "kms:EncryptionContext:aws:cognito-idp:userpool-arn"
            ]
            self.assertEqual(len(context), 2)
            for pool_region, arn in zip(("us-east-1", "us-west-2"), context):
                self.assertIn(f":cognito-idp:{pool_region}:123456789012:userpool/*", json.dumps(arn))


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
            updated_issuer=primary.updated_issuer,
            replica_credentials_key=replica_configuration.credentials_key,
            env=primary_env, cross_region_references=True,
        )
        replica_parameters = CognitoReplicaCredentialsParametersStack(
            app, "ReplicaCredentialsParameters",
            credentials=credentials.credentials,
            updated_issuer=primary.updated_issuer,
            replica_credentials_key=replica_configuration.credentials_key,
            env=replica_env, cross_region_references=True,
        )
        primary_resources = Template.from_stack(primary).to_json()["Resources"]
        primary_risk = primary_resources["UserPoolRiskConfiguration"]["Properties"]
        self.assertEqual(primary_risk["ClientId"], "ALL")
        self.assertEqual(
            primary_risk["CompromisedCredentialsRiskConfiguration"],
            {
                "Actions": {"EventAction": "BLOCK"},
                "EventFilter": ["SIGN_IN", "SIGN_UP", "PASSWORD_CHANGE"],
            },
        )
        takeover = primary_risk["AccountTakeoverRiskConfiguration"]
        self.assertEqual(
            takeover["Actions"],
            {
                "LowAction": {"EventAction": "NO_ACTION", "Notify": False},
                "MediumAction": {"EventAction": "NO_ACTION", "Notify": False},
                "HighAction": {"EventAction": "BLOCK", "Notify": True},
            },
        )
        self.assertEqual(
            takeover["NotifyConfiguration"]["SourceArn"],
            "arn:aws:ses:us-east-1:123456789012:identity/auth.4n6ir.com",
        )
        replica_resources = Template.from_stack(replica_configuration).to_json()["Resources"]
        self.assertFalse(any(
            resource["Type"] == "AWS::Cognito::UserPoolRiskConfigurationAttachment"
            for resource in replica_resources.values()
        ))
        risk_resource = next(
            resource for name, resource in replica_resources.items()
            if name.startswith("UserPoolRiskConfiguration")
            and resource["Type"] == "Custom::AWS"
        )
        self.assertIn("UserPoolReplicaConfiguration", risk_resource["DependsOn"])
        properties = risk_resource["Properties"]
        self.assertNotIn("Delete", properties)
        calls = []
        for operation in ("Create", "Update"):
            parts = properties[operation]["Fn::Join"][1]
            call = json.loads("".join(
                part if isinstance(part, str) else "pool-id" for part in parts
            ))
            self.assertEqual(call["service"], "@aws-sdk/client-cognito-identity-provider")
            self.assertEqual(call["action"], "setRiskConfiguration")
            self.assertNotIn("ClientId", call["parameters"])
            calls.append(call)
        self.assertEqual(calls[0], calls[1])
        replica_risk = calls[0]["parameters"]
        self.assertEqual(
            replica_risk["CompromisedCredentialsRiskConfiguration"],
            primary_risk["CompromisedCredentialsRiskConfiguration"],
        )
        replica_takeover = replica_risk["AccountTakeoverRiskConfiguration"]
        self.assertEqual(replica_takeover["Actions"], takeover["Actions"])
        replica_notification = replica_takeover["NotifyConfiguration"].copy()
        self.assertEqual(
            replica_notification.pop("SourceArn"),
            "arn:aws:ses:us-west-2:123456789012:identity/auth.4n6ir.com",
        )
        self.assertEqual(
            replica_notification,
            {key: value for key, value in takeover["NotifyConfiguration"].items()
             if key != "SourceArn"},
        )
        policy = next(
            resource for name, resource in replica_resources.items()
            if name.startswith("UserPoolRiskConfigurationCustomResourcePolicy")
            and resource["Type"] == "AWS::IAM::Policy"
        )["Properties"]["PolicyDocument"]["Statement"]
        decrypt = next(statement for statement in policy if statement["Action"] == "kms:Decrypt")
        self.assertNotEqual(decrypt["Resource"], "*")
        self.assertEqual(
            decrypt["Condition"]["StringEquals"]["kms:ViaService"],
            {"Fn::Join": ["", ["cognito-idp.us-west-2.", {"Ref": "AWS::URLSuffix"}]]},
        )
        self.assertIn(
            "kms:EncryptionContext:aws:cognito-idp:userpool-arn",
            decrypt["Condition"]["StringLike"],
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
        secret_parts = secret["SecretString"]["Fn::Join"][1]
        self.assertEqual(
            json.loads("".join(
                part if isinstance(part, str) else (
                    "client-id" if part == {"Ref": "EdgeAppClient"} else "client-secret"
                )
                for part in secret_parts
            )),
            {"Dashboard": {"CLIENT_ID": "client-id", "CLIENT_SECRET": "client-secret"}},
        )
        self.assertIn({"Fn::GetAtt": ["EdgeAppClient", "ClientSecret"]}, secret_parts)
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
        for stack, region in (
            (credentials, "us-east-1"),
            (replica_parameters, "us-west-2"),
        ):
            template = Template.from_stack(stack).to_json()
            domains_parameter = next(
                name for name, value in template["Parameters"].items()
                if value.get("Default") == "/account/domains"
            )
            parameters = {
                resource["Properties"]["Name"]: (name, resource["Properties"])
                for name, resource in template["Resources"].items()
                if resource["Type"] == "AWS::SSM::Parameter"
            }
            self.assertEqual(
                set(parameters),
                {"/cognito/encrypt", "/cognito/secret", "/cognito/issuer"},
            )
            for _, parameter in parameters.values():
                self.assertEqual(parameter["Tier"], "Advanced")
                self.assertEqual(parameter["Type"], "String")
            self.assertEqual(
                parameters["/cognito/issuer"][1]["Value"],
                stack.resolve(primary.updated_issuer),
            )
            share = next(
                resource for resource in template["Resources"].values()
                if resource["Type"] == "AWS::RAM::ResourceShare"
            )
            self.assertEqual(share["Properties"]["Principals"], [{"Ref": domains_parameter}])
            self.assertEqual(set(share["DependsOn"]), {item[0] for item in parameters.values()})
            self.assertEqual(len(share["Properties"]["ResourceArns"]), 3)
            for parameter_id, _ in parameters.values():
                self.assertIn(json.dumps({"Ref": parameter_id}), json.dumps(share["Properties"]["ResourceArns"]))
            self.assertIn(region, json.dumps(share["Properties"]["ResourceArns"]))
        primary_parameters = {
            resource["Properties"]["Name"]: resource["Properties"]["Value"]
            for resource in credential_resources.values()
            if resource["Type"] == "AWS::SSM::Parameter"
        }
        secret_id = next(
            name for name, resource in credential_resources.items()
            if resource["Type"] == "AWS::SecretsManager::Secret"
        )
        key_id = next(
            name for name, resource in credential_resources.items()
            if resource["Type"] == "AWS::KMS::Key" and name.startswith("CredentialsKey")
        )
        self.assertEqual(primary_parameters["/cognito/secret"], {"Ref": secret_id})
        self.assertEqual(primary_parameters["/cognito/encrypt"], {"Fn::GetAtt": [key_id, "Arn"]})
        replica_template = Template.from_stack(replica_parameters).to_json()
        replica_values = {
            resource["Properties"]["Name"]: resource["Properties"]["Value"]
            for resource in replica_template["Resources"].values()
            if resource["Type"] == "AWS::SSM::Parameter"
        }
        replica_secret_value = json.dumps(replica_values["/cognito/secret"])
        self.assertIn(":secretsmanager:us-west-2:", replica_secret_value)
        self.assertIn('"Fn::Select": [6, {"Fn::Split": [":"', replica_secret_value)
        self.assertIn(secret_id, replica_secret_value)
        self.assertIn("CredentialsKey", json.dumps(replica_values["/cognito/encrypt"]))
        self.assertIn(credentials, replica_parameters.dependencies)
        self.assertIn(replica_configuration, replica_parameters.dependencies)
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
        self.assertEqual(
            issuer,
            replica_configuration.resolve(primary.updated_issuer),
        )
        self.assertEqual(
            Template.from_stack(primary).to_json()["Outputs"]["UpdatedIssuer"]["Value"],
            {
                "Fn::Join": [
                    "",
                    [
                        "https://issuer-cognito-idp.us-east-1.amazonaws.com/",
                        {"Ref": "UserPool"},
                    ],
                ]
            },
        )


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
            updated_issuer=idp.updated_issuer,
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
