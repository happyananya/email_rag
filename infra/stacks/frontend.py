"""Layer 1 (frontend): S3 + CloudFront (+ optional Route 53 / ACM custom domain)."""

from pathlib import Path

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

FRONTEND_BUILD = Path(__file__).resolve().parents[2] / "frontend" / "out"


class FrontendStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        domain_name = self.node.try_get_context("domainName")
        zone_name = self.node.try_get_context("hostedZoneName")

        bucket = s3.Bucket(
            self,
            "WebBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        cert = zone = None
        if domain_name and zone_name:
            # CloudFront certificates must live in us-east-1: deploy this stack there.
            zone = route53.HostedZone.from_lookup(self, "Zone", domain_name=zone_name)
            cert = acm.Certificate(
                self, "Cert", domain_name=domain_name,
                validation=acm.CertificateValidation.from_dns(zone),
            )

        route_rewrite = cloudfront.Function(
            self,
            "RouteRewrite",
            runtime=cloudfront.FunctionRuntime.JS_2_0,
            code=cloudfront.FunctionCode.from_inline(
                """function handler(event) {
  var request = event.request;
  var uri = request.uri;
  if (uri.slice(-1) === '/') {
    request.uri = uri + 'index.html';
  } else if (uri.indexOf('.') === -1) {
    request.uri = uri + '/index.html';
  }
  return request;
}"""
            ),
        )

        dist = cloudfront.Distribution(
            self,
            "Cdn",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
                function_associations=[cloudfront.FunctionAssociation(
                    function=route_rewrite,
                    event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                )],
            ),
            error_responses=[
                cloudfront.ErrorResponse(http_status=403, response_http_status=404,
                                         response_page_path="/404.html"),
            ],
            domain_names=[domain_name] if cert else None,
            certificate=cert,
            minimum_protocol_version=(
                cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021 if cert else None
            ),
        )

        if zone:
            route53.ARecord(
                self, "Alias", zone=zone, record_name=domain_name,
                target=route53.RecordTarget.from_alias(targets.CloudFrontTarget(dist)),
            )

        # Deploy the static Next.js export if it has been built (`make frontend-build`).
        if FRONTEND_BUILD.exists():
            s3deploy.BucketDeployment(
                self, "DeployWeb",
                sources=[s3deploy.Source.asset(str(FRONTEND_BUILD))],
                destination_bucket=bucket,
                distribution=dist,
                distribution_paths=["/*"],
            )

        self.url = f"https://{domain_name}" if cert else f"https://{dist.distribution_domain_name}"
        CfnOutput(self, "WebUrl", value=self.url)
        CfnOutput(self, "WebBucketName", value=bucket.bucket_name)
        CfnOutput(self, "DistributionId", value=dist.distribution_id)
