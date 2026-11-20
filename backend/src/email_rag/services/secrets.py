"""Secrets Manager helpers: per-account OAuth tokens and app secrets."""

import json
from functools import lru_cache
from typing import Any

import boto3

_sm = None


def _client():
    global _sm
    if _sm is None:
        _sm = boto3.client("secretsmanager")
    return _sm


def oauth_secret_name(user_id: str, email_address: str) -> str:
    return f"email-rag/oauth/{user_id}/{email_address}"


def put_oauth_tokens(user_id: str, email_address: str, tokens: dict[str, Any]) -> str:
    """Create or update the token secret; returns its ARN."""
    name = oauth_secret_name(user_id, email_address)
    body = json.dumps(tokens)
    try:
        return _client().create_secret(
            Name=name, SecretString=body, Tags=[{"Key": "user_id", "Value": user_id}]
        )["ARN"]
    except _client().exceptions.ResourceExistsException:
        return _client().put_secret_value(SecretId=name, SecretString=body)["ARN"]


def get_json(secret_id: str) -> dict[str, Any]:
    return json.loads(_client().get_secret_value(SecretId=secret_id)["SecretString"])


def update_json(secret_id: str, value: dict[str, Any]) -> None:
    _client().put_secret_value(SecretId=secret_id, SecretString=json.dumps(value))


def delete_secret(secret_id: str) -> None:
    _client().delete_secret(SecretId=secret_id, ForceDeleteWithoutRecovery=True)


@lru_cache
def get_cached_json(secret_id: str) -> dict[str, Any]:
    """For app-level secrets (Google client creds, webhook token) that rarely change."""
    return get_json(secret_id)
