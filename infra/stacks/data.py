"""Layer 4 (data) + Layer 5 (secrets/crypto): VPC, Aurora PostgreSQL + pgvector, S3, KMS, secrets."""

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_kms as kms
from aws_cdk import aws_rds as rds
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as sm
from constructs import Construct


class DataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.key = kms.Key(
            self, "DataKey", alias="alias/email-rag-data", enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # One NAT gateway keeps cost down; Lambdas need egress to reach the Gmail API.
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                ec2.SubnetConfiguration(
                    name="app", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, cidr_mask=22
                ),
                ec2.SubnetConfiguration(
                    name="db", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24
                ),
            ],
        )
        self.vpc.add_gateway_endpoint("S3Endpoint", service=ec2.GatewayVpcEndpointAwsService.S3)

        self.lambda_sg = ec2.SecurityGroup(
            self, "LambdaSg", vpc=self.vpc, description="Email RAG Lambdas"
        )

        self.db = rds.DatabaseCluster(
            self,
            "Db",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_16_4
            ),
            writer=rds.ClusterInstance.serverless_v2("writer"),
            serverless_v2_min_capacity=0.5,
            serverless_v2_max_capacity=4,
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            credentials=rds.Credentials.from_generated_secret("emailrag", secret_name="email-rag/db"),
            default_database_name="emailrag",
            storage_encrypted=True,
            storage_encryption_key=self.key,
            removal_policy=RemovalPolicy.SNAPSHOT,
        )
        self.db.connections.allow_default_port_from(self.lambda_sg, "Lambdas to Aurora")

        self.email_bucket = s3.Bucket(
            self,
            "EmailBucket",
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Fill in after deploy: {"client_id": "...", "client_secret": "..."} (see README).
        self.google_client_secret = sm.Secret(
            self, "GoogleOAuthClient",
            secret_name="email-rag/google-oauth-client",
            description='Google OAuth client: {"client_id": "...", "client_secret": "..."}',
        )
        # Shared token appended to the Pub/Sub push endpoint URL (?token=...).
        self.webhook_secret = sm.Secret(
            self, "GmailWebhookToken",
            secret_name="email-rag/gmail-webhook",
            generate_secret_string=sm.SecretStringGenerator(
                secret_string_template="{}", generate_string_key="token",
                exclude_punctuation=True, password_length=40,
            ),
        )

        CfnOutput(self, "EmailBucketName", value=self.email_bucket.bucket_name)
        CfnOutput(self, "DbSecretArn", value=self.db.secret.secret_arn)
