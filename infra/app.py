#!/usr/bin/env python3
"""CDK app for the Email RAG SaaS platform (single region, five layers)."""

import os

import aws_cdk as cdk

from stacks.auth import AuthStack
from stacks.backend import BackendStack
from stacks.data import DataStack
from stacks.frontend import FrontendStack

app = cdk.App()
stage = app.node.try_get_context("stage") or "dev"
env = cdk.Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT"),
    region=os.getenv("CDK_DEFAULT_REGION", "us-east-1"),
)
prefix = f"EmailRag-{stage}"

frontend = FrontendStack(app, f"{prefix}-Frontend", env=env)
auth = AuthStack(app, f"{prefix}-Auth", env=env)
data = DataStack(app, f"{prefix}-Data", env=env)
BackendStack(
    app,
    f"{prefix}-Backend",
    env=env,
    data=data,
    auth=auth,
    frontend_url=frontend.url,
)

cdk.Tags.of(app).add("project", "email-rag")
cdk.Tags.of(app).add("stage", stage)
app.synth()
