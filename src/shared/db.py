"""DynamoDB resource helpers and update expression builder."""

from datetime import datetime, timezone

import boto3

from shared.config import AWS_REGION, BLOG_TABLE, DYNAMODB_KWARGS, PLAYBOOK_TABLE


def _dynamodb():
    return boto3.resource("dynamodb", region_name=AWS_REGION, **DYNAMODB_KWARGS)


def get_blog_table():
    return _dynamodb().Table(BLOG_TABLE)


def get_playbook_table():
    return _dynamodb().Table(PLAYBOOK_TABLE)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_update_expression(data: dict) -> tuple[str, dict, dict]:
    """
    Build a DynamoDB SET expression from a flat dict of {field: value}.

    Returns (UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues).

    All attribute names are aliased via ExpressionAttributeNames to avoid
    conflicts with DynamoDB reserved words (e.g. status, date, content).
    """
    parts: list[str] = []
    names: dict[str, str] = {}
    values: dict[str, object] = {}

    for i, (key, value) in enumerate(data.items()):
        name_ph = f"#k{i}"
        val_ph = f":v{i}"
        parts.append(f"{name_ph} = {val_ph}")
        names[name_ph] = key
        values[val_ph] = value

    return "SET " + ", ".join(parts), names, values
