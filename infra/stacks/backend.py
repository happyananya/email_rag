"""Layers 2, 3 and 5: API Gateway + Lambdas, Step Functions backfill, EventBridge schedule,
SQS ingestion queue + DLQ, Bedrock access, and CloudWatch alarms / budget."""

import subprocess
import sys
import tempfile
from pathlib import Path

import jsii
from aws_cdk import CfnOutput, Duration, ILocalBundling, RemovalPolicy, Stack, triggers
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as events_targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as event_sources
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

from stacks.auth import AuthStack
from stacks.data import DataStack

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
PIP_TARGET_FLAGS = (
    "--platform manylinux2014_aarch64 --implementation cp --python-version 3.12 --only-binary=:all:"
)


@jsii.implements(ILocalBundling)
class LocalPipBundling:
    """Bundle Lambda code with the host's pip (no Docker needed). Builds the backend wheel, then
    installs it plus Linux arm64 wheels of its dependencies into the asset directory."""

    def try_bundle(self, output_dir: str, options=None, **_kwargs) -> bool:
        with tempfile.TemporaryDirectory() as wheel_dir:
            pip = [sys.executable, "-m", "pip", "--disable-pip-version-check", "-q"]
            subprocess.run([*pip, "wheel", str(BACKEND_DIR), "--no-deps", "-w", wheel_dir], check=True)
            wheels = [str(p) for p in Path(wheel_dir).glob("*.whl")]
            subprocess.run(
                [*pip, "install", *wheels, "--target", output_dir, *PIP_TARGET_FLAGS.split()],
                check=True,
            )
        return True


class BackendStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        data: DataStack,
        auth: AuthStack,
        frontend_url: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ---------------- Ingestion queue + DLQ (layer 3) ----------------
        dlq = sqs.Queue(
            self, "IngestDlq", retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
        )
        queue = sqs.Queue(
            self, "IngestQueue",
            visibility_timeout=Duration.minutes(6),  # >= 6x worker timeout guidance
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            dead_letter_queue=sqs.DeadLetterQueue(queue=dlq, max_receive_count=4),
        )

        # ---------------- Shared Lambda config ----------------
        # Cross-platform bundling: build our pure-Python wheel, then fetch arm64 wheels for deps.
        # Runs locally with pip; falls back to the Lambda build image in Docker if that fails.
        code = lambda_.Code.from_asset(
            str(BACKEND_DIR),
            exclude=[".venv", "build", "tests", "**/__pycache__", ".pytest_cache", ".ruff_cache",
                     "**/*.egg-info"],
            bundling={
                "image": lambda_.Runtime.PYTHON_3_12.bundling_image,
                "local": LocalPipBundling(),
                "environment": {"PIP_CACHE_DIR": "/tmp/pip-cache", "HOME": "/tmp"},
                "command": [
                    "bash", "-c",
                    "pip wheel . --no-deps -w /tmp/wheel && "
                    f"pip install /tmp/wheel/*.whl --target /asset-output {PIP_TARGET_FLAGS}",
                ],
            },
        )

        env = {
            "DB_SECRET_ARN": data.db.secret.secret_arn,
            "EMAIL_BUCKET": data.email_bucket.bucket_name,
            "INGEST_QUEUE_URL": queue.queue_url,
            "GOOGLE_CLIENT_SECRET_ARN": data.google_client_secret.secret_arn,
            "WEBHOOK_SECRET_ARN": data.webhook_secret.secret_arn,
            "FRONTEND_URL": frontend_url,
            "OAUTH_REDIRECT_URI": f"{frontend_url}/auth/callback",
            "GMAIL_PUBSUB_TOPIC": self.node.try_get_context("gmailPubsubTopic") or "",
            "LLM_MODEL_ID": self.node.try_get_context("llmModelId")
            or "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            "EMBEDDING_MODEL_ID": "amazon.titan-embed-text-v2:0",
            "EMBEDDING_DIMENSIONS": "1024",
            "POWERTOOLS_SERVICE_NAME": "email-rag",
        }

        def fn(name: str, handler: str, timeout: Duration, memory: int = 512, **extra) -> lambda_.Function:
            f = lambda_.Function(
                self, name,
                runtime=lambda_.Runtime.PYTHON_3_12,
                architecture=lambda_.Architecture.ARM_64,
                code=code,
                handler=handler,
                timeout=timeout,
                memory_size=memory,
                environment=env,
                vpc=data.vpc,
                vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
                security_groups=[data.lambda_sg],
                tracing=lambda_.Tracing.ACTIVE,
                log_group=logs.LogGroup(self, f"{name}Logs", retention=logs.RetentionDays.ONE_MONTH),
                **extra,
            )
            data.db.secret.grant_read(f)
            data.email_bucket.grant_read_write(f)
            data.google_client_secret.grant_read(f)
            f.add_to_role_policy(oauth_secrets_policy)
            return f

        oauth_secrets_policy = iam.PolicyStatement(
            actions=[
                "secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue",
                "secretsmanager:CreateSecret", "secretsmanager:DeleteSecret",
                "secretsmanager:TagResource",
            ],
            resources=[f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:email-rag/oauth/*"],
        )
        embedding_policy = iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[
                f"arn:{self.partition}:bedrock:{self.region}::foundation-model/"
                f"{env['EMBEDDING_MODEL_ID']}"
            ],
        )
        llm_model_id = env["LLM_MODEL_ID"]
        if llm_model_id.startswith("us."):
            foundation_model_id = llm_model_id.removeprefix("us.")
            llm_resources = [
                f"arn:{self.partition}:bedrock:{self.region}:{self.account}:"
                f"inference-profile/{llm_model_id}",
                *[
                    f"arn:{self.partition}:bedrock:{region}::foundation-model/{foundation_model_id}"
                    for region in ("us-east-1", "us-east-2", "us-west-2")
                ],
            ]
        else:
            llm_resources = [
                f"arn:{self.partition}:bedrock:{self.region}::foundation-model/{llm_model_id}"
            ]
        llm_policy = iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=llm_resources,
        )

        api_fn = fn("ApiFn", "email_rag.handlers.api.handler", Duration.seconds(29), memory=1024)
        sync_fn = fn("SyncFn", "email_rag.handlers.sync.handler", Duration.minutes(5))
        worker_fn = fn("WorkerFn", "email_rag.handlers.worker.handler", Duration.minutes(1), memory=1024)
        backfill_fn = fn("BackfillFn", "email_rag.handlers.backfill.handler", Duration.minutes(2))
        migrate_fn = fn("MigrateFn", "email_rag.handlers.migrate.handler", Duration.minutes(5))

        for f in (api_fn, worker_fn):
            f.add_to_role_policy(embedding_policy)
        api_fn.add_to_role_policy(llm_policy)
        for f in (sync_fn, backfill_fn):
            queue.grant_send_messages(f)
        data.webhook_secret.grant_read(sync_fn)

        worker_fn.add_event_source(event_sources.SqsEventSource(
            queue, batch_size=5, max_batching_window=Duration.seconds(5),
            report_batch_item_failures=True,
            max_concurrency=2,  # protect Gmail's per-user quota during large backfills/redrives
        ))

        # Run DB migrations whenever the migration code changes.
        triggers.Trigger(self, "MigrateOnDeploy", handler=migrate_fn, timeout=Duration.minutes(5))

        # ---------------- Backfill workflow (Step Functions) ----------------
        def invoke(id_: str, payload: dict) -> tasks.LambdaInvoke:
            t = tasks.LambdaInvoke(
                self, id_, lambda_function=backfill_fn,
                payload=sfn.TaskInput.from_object(payload), payload_response_only=True,
            )
            t.add_retry(errors=["States.ALL"], max_attempts=4, backoff_rate=2,
                        interval=Duration.seconds(5))
            return t

        start = invoke("Start", {"step": "start", "account_id.$": "$.account_id"})
        list_page = invoke("ListPage", {
            "step": "list_page", "account_id.$": "$.account_id",
            "page_token.$": "$.page_token", "queued.$": "$.queued",
        })
        finish = invoke("Finish", {"step": "finish", "account_id.$": "$.account_id",
                                   "queued.$": "$.queued"})
        mark_error = tasks.LambdaInvoke(
            self, "MarkBackfillError", lambda_function=backfill_fn,
            payload=sfn.TaskInput.from_object({
                "step": "fail", "account_id.$": "$.account_id", "error.$": "$.error",
            }),
            payload_response_only=True,
        )
        for task in (start, list_page, finish):
            task.add_catch(mark_error, errors=["States.ALL"], result_path="$.error")
        more = (sfn.Choice(self, "MorePages")
                .when(sfn.Condition.boolean_equals("$.done", True), finish)
                .otherwise(list_page))
        backfill = sfn.StateMachine(
            self, "Backfill",
            definition_body=sfn.DefinitionBody.from_chainable(start.next(list_page).next(more)),
            timeout=Duration.hours(6),
            tracing_enabled=True,
        )
        backfill.grant_start_execution(api_fn)
        backfill.grant_start_execution(sync_fn)
        api_fn.add_environment("BACKFILL_STATE_MACHINE_ARN", backfill.state_machine_arn)
        sync_fn.add_environment("BACKFILL_STATE_MACHINE_ARN", backfill.state_machine_arn)

        # ---------------- Scheduled incremental sync (EventBridge) ----------------
        events.Rule(
            self, "SyncSchedule",
            schedule=events.Schedule.rate(Duration.minutes(15)),
            targets=[events_targets.LambdaFunction(sync_fn)],
        )

        # ---------------- REST API (API Gateway + Cognito authorizer) ----------------
        api_access_logs = logs.LogGroup(
            self,
            "ApiAccessLogs",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        api = apigw.RestApi(
            self, "Api",
            rest_api_name="email-rag-api",
            deploy_options=apigw.StageOptions(
                stage_name="v1", tracing_enabled=True, metrics_enabled=True,
                throttling_rate_limit=50, throttling_burst_limit=100,
                access_log_destination=apigw.LogGroupLogDestination(api_access_logs),
                access_log_format=apigw.AccessLogFormat.json_with_standard_fields(
                    caller=False,
                    http_method=True,
                    ip=True,
                    protocol=True,
                    request_time=True,
                    resource_path=True,
                    response_length=True,
                    status=True,
                    user=True,
                ),
            ),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=[frontend_url, "http://localhost:3000"],
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=["Authorization", "Content-Type"],
            ),
        )
        authorizer = apigw.CognitoUserPoolsAuthorizer(
            self, "CognitoAuth", cognito_user_pools=[auth.user_pool]
        )
        proxy = api.root.add_resource("{proxy+}")
        proxy.add_method(
            "ANY", apigw.LambdaIntegration(api_fn),
            authorizer=authorizer, authorization_type=apigw.AuthorizationType.COGNITO,
        )
        # Gmail push (Pub/Sub) webhook: unauthenticated at the gateway, verified by shared token.
        api.root.add_resource("webhooks").add_resource("gmail").add_method(
            "POST", apigw.LambdaIntegration(sync_fn), authorization_type=apigw.AuthorizationType.NONE,
        )

        # ---------------- Monitoring (CloudWatch alarms + budget) ----------------
        alarm_topic = sns.Topic(self, "Alarms")
        alarm_email = self.node.try_get_context("alarmEmail")
        if alarm_email:
            alarm_topic.add_subscription(subs.EmailSubscription(alarm_email))
        notify = cw_actions.SnsAction(alarm_topic)

        alarms = [
            dlq.metric_approximate_number_of_messages_visible().create_alarm(
                self, "DlqNotEmpty", threshold=1, evaluation_periods=1,
                alarm_description="Emails failed ingestion after retries",
            ),
            queue.metric_approximate_age_of_oldest_message().create_alarm(
                self, "QueueBacklog", threshold=900, evaluation_periods=3,
                alarm_description="Ingestion queue is falling behind (>15 min)",
            ),
            api.metric_server_error(period=Duration.minutes(5)).create_alarm(
                self, "Api5xx", threshold=5, evaluation_periods=1,
            ),
        ]
        for name, f in {"Api": api_fn, "Sync": sync_fn, "Worker": worker_fn, "Backfill": backfill_fn}.items():
            alarms.append(f.metric_errors(period=Duration.minutes(5)).create_alarm(
                self, f"{name}Errors", threshold=5, evaluation_periods=1,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            ))
        for a in alarms:
            a.add_alarm_action(notify)

        dashboard = cw.Dashboard(
            self, "OperationsDashboard", dashboard_name=f"{self.stack_name}-Ops"
        )
        dashboard.add_widgets(
            cw.GraphWidget(
                title="API latency",
                left=[
                    api.metric_latency(statistic="p50", period=Duration.minutes(5)),
                    api.metric_latency(statistic="p90", period=Duration.minutes(5)),
                ],
            ),
            cw.GraphWidget(
                title="API and Lambda errors",
                left=[api.metric_server_error(period=Duration.minutes(5))]
                + [
                    f.metric_errors(period=Duration.minutes(5))
                    for f in (api_fn, sync_fn, worker_fn, backfill_fn)
                ],
            ),
        )
        dashboard.add_widgets(
            cw.GraphWidget(
                title="Lambda duration p90",
                left=[
                    f.metric_duration(statistic="p90", period=Duration.minutes(5))
                    for f in (api_fn, sync_fn, worker_fn, backfill_fn)
                ],
            ),
            cw.GraphWidget(
                title="Ingestion queue",
                left=[
                    queue.metric_approximate_number_of_messages_visible(),
                    queue.metric_approximate_number_of_messages_not_visible(),
                    dlq.metric_approximate_number_of_messages_visible(),
                ],
                right=[queue.metric_approximate_age_of_oldest_message()],
            ),
        )
        dashboard.add_widgets(
            cw.GraphWidget(
                title="Bedrock latency and throttles",
                left=[
                    cw.Metric(
                        namespace="AWS/Bedrock",
                        metric_name="InvocationLatency",
                        dimensions_map={"ModelId": env["LLM_MODEL_ID"]},
                        statistic="p90",
                        period=Duration.minutes(5),
                    )
                ],
                right=[
                    cw.Metric(
                        namespace="AWS/Bedrock",
                        metric_name="InvocationThrottles",
                        dimensions_map={"ModelId": env["LLM_MODEL_ID"]},
                        statistic="Sum",
                        period=Duration.minutes(5),
                    )
                ],
            )
        )

        budget_usd = float(self.node.try_get_context("budgetUsd") or 50)
        if alarm_email:
            budgets.CfnBudget(
                self, "MonthlyBudget",
                budget=budgets.CfnBudget.BudgetDataProperty(
                    budget_type="COST", time_unit="MONTHLY",
                    budget_limit=budgets.CfnBudget.SpendProperty(amount=budget_usd, unit="USD"),
                ),
                notifications_with_subscribers=[
                    budgets.CfnBudget.NotificationWithSubscribersProperty(
                        notification=budgets.CfnBudget.NotificationProperty(
                            comparison_operator="GREATER_THAN", notification_type="ACTUAL",
                            threshold=80, threshold_type="PERCENTAGE",
                        ),
                        subscribers=[budgets.CfnBudget.SubscriberProperty(
                            subscription_type="EMAIL", address=alarm_email)],
                    )
                ],
            )

        CfnOutput(self, "ApiUrl", value=api.url)
        CfnOutput(self, "GmailWebhookPath", value=f"{api.url}webhooks/gmail?token=<email-rag/gmail-webhook token>")
        CfnOutput(self, "IngestQueueUrl", value=queue.queue_url)
        CfnOutput(self, "IngestDlqUrl", value=dlq.queue_url)
        CfnOutput(self, "IngestDlqArn", value=dlq.queue_arn)
        CfnOutput(self, "OperationsDashboardName", value=dashboard.dashboard_name)
