#!/usr/bin/env python3
"""
Print the deployed AgentCore invocation URL for this project.

Preferred path:
- Query the latest AgentCore CLI project state with `fetch access`

Fallback path:
- If the CLI is unavailable or the project is not deployed yet, accept an ARN
  and derive the invocation URL directly.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

from boto3.session import Session


PROJECT_ROOT = Path(__file__).resolve().parent
AGENTCORE_CLI = PROJECT_ROOT / "deployment" / "agentcore_cli.sh"


def build_agent_url(agent_arn: str) -> str:
    session = Session()
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or session.region_name or "us-west-2"
    endpoint = f"https://bedrock-agentcore.{region}.amazonaws.com"
    escaped = urllib.parse.quote(agent_arn, safe="")
    return f"{endpoint}/runtimes/{escaped}/invocations?qualifier=DEFAULT"


def parse_cli_json(output: str):
    cleaned = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", output or "").strip()
    json_start = min(
        [idx for idx in (cleaned.find("{"), cleaned.find("[")) if idx != -1],
        default=-1,
    )
    if json_start == -1:
        return None
    cleaned = cleaned[json_start:]
    json_end = cleaned.rfind("}" if cleaned.startswith("{") else "]")
    if json_end == -1:
        return None
    try:
        return json.loads(cleaned[: json_end + 1])
    except json.JSONDecodeError:
        return None


def find_url(payload):
    if isinstance(payload, dict):
        for key in ("url", "invokeUrl", "endpointUrl", "invocationUrl"):
            value = payload.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
        for value in payload.values():
            result = find_url(value)
            if result:
                return result
    elif isinstance(payload, list):
        for value in payload:
            result = find_url(value)
            if result:
                return result
    return None


def fetch_project_url(resource_name: str) -> str | None:
    if not AGENTCORE_CLI.exists():
        return None

    try:
        output = subprocess.check_output(
            [
                str(AGENTCORE_CLI),
                "fetch",
                "access",
                "--type",
                "agent",
                "--name",
                resource_name,
                "--json",
            ],
            cwd=PROJECT_ROOT,
            text=True,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as exc:
        print(exc.output.strip(), file=sys.stderr)
        return None

    try:
        payload = parse_cli_json(output)
    except json.JSONDecodeError:
        return None
    if payload is None:
        return None

    return find_url(payload)


def fetch_runtime_identifier(resource_name: str) -> str | None:
    if not AGENTCORE_CLI.exists():
        return None

    try:
        output = subprocess.check_output(
            [
                str(AGENTCORE_CLI),
                "status",
                "--runtime",
                resource_name,
                "--json",
            ],
            cwd=PROJECT_ROOT,
            text=True,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as exc:
        print(exc.output.strip(), file=sys.stderr)
        return None

    payload = parse_cli_json(output)
    if not isinstance(payload, dict):
        return None

    for item in payload.get("resources", []):
        if item.get("name") == resource_name and item.get("identifier"):
            return item["identifier"]
    return None


def main() -> None:
    resource_name = sys.argv[1] if len(sys.argv) > 1 else "AgentWatch"
    project_url = fetch_project_url(resource_name)
    if project_url:
        print("\nInvocation URL:\n", project_url)
        return

    runtime_identifier = fetch_runtime_identifier(resource_name)
    if runtime_identifier:
        print("\nInvocation URL:\n", build_agent_url(runtime_identifier))
        return

    arn = input(
        "AgentCore fetch access was unavailable. Enter your Bedrock AgentCore ARN: "
    ).strip()
    if not arn:
        print("No ARN provided. Exiting.")
        return

    url = build_agent_url(arn)
    print("\nInvocation URL:\n", url)


if __name__ == "__main__":
    main()
