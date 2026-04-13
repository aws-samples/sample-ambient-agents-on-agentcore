#!/usr/bin/env python3
"""
Hydrate AgentCore project config for the current AWS account and optional Cognito auth.

This keeps the committed repo generic while letting each developer sync:
1. agentcore/aws-targets.json to the active AWS account and region
2. agentcore/agentcore.json with CUSTOM_JWT auth from either:
   - cognito_config.json produced by idp_setup/setup_cognito.py
   - CloudFormation stack outputs
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import boto3  # type: ignore
except ImportError:  # pragma: no cover - fallback path for bare system Python
    boto3 = None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def dump_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


def get_session_region() -> str:
    for env_name in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        env_region = os.environ.get(env_name)
        if env_region:
            return env_region

    if boto3 is not None:
        session = boto3.session.Session()
        if session.region_name:
            return session.region_name

    try:
        region = (
            subprocess.check_output(
                ["aws", "configure", "get", "region"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            .strip()
        )
        if region:
            return region
    except Exception:
        pass

    return "us-west-2"


def aws_cli_json(args: list[str]) -> Dict[str, Any]:
    raw = subprocess.check_output(["aws", *args], text=True)
    return json.loads(raw)


def get_account_id(region: str) -> str:
    if boto3 is not None:
        sts = boto3.client("sts", region_name=region)
        return sts.get_caller_identity()["Account"]
    return aws_cli_json(["sts", "get-caller-identity", "--region", region])["Account"]


def build_auth_from_cognito_config(config_path: Path) -> Dict[str, Any]:
    cognito = load_json(config_path)
    discovery_url = cognito.get("discovery_url")
    if not discovery_url and cognito.get("pool_id"):
        region = cognito["pool_id"].split("_", 1)[0]
        discovery_url = (
            f"https://cognito-idp.{region}.amazonaws.com/"
            f"{cognito['pool_id']}/.well-known/openid-configuration"
        )

    allowed_client = cognito.get("m2m_client_id") or cognito.get("client_id")
    resource_server_id = cognito.get("resource_server_id")

    if not discovery_url or not allowed_client:
        raise ValueError(
            f"{config_path} is missing one of discovery_url or m2m_client_id/client_id"
        )

    auth_config: Dict[str, Any] = {
        "discoveryUrl": discovery_url,
        "allowedClients": [allowed_client],
    }
    if resource_server_id:
        auth_config["allowedScopes"] = [f"{resource_server_id}/gateway:read"]
    return auth_config


def build_auth_from_stack(stack_name: str, region: str) -> Dict[str, Any]:
    if boto3 is not None:
        cfn = boto3.client("cloudformation", region_name=region)
        stacks = cfn.describe_stacks(StackName=stack_name)["Stacks"]
    else:
        stacks = aws_cli_json(
            ["cloudformation", "describe-stacks", "--stack-name", stack_name, "--region", region]
        )["Stacks"]
    outputs = {
        entry["OutputKey"]: entry["OutputValue"]
        for entry in stacks[0].get("Outputs", [])
    }

    user_pool_id = outputs.get("CognitoUserPoolId")
    client_id = outputs.get("M2MClientId")
    resource_server_id = outputs.get("ResourceServerId")

    if not user_pool_id or not client_id:
        raise ValueError(
            f"Stack {stack_name} is missing CognitoUserPoolId or M2MClientId outputs"
        )

    discovery_url = (
        f"https://cognito-idp.{region}.amazonaws.com/"
        f"{user_pool_id}/.well-known/openid-configuration"
    )

    auth_config: Dict[str, Any] = {
        "discoveryUrl": discovery_url,
        "allowedClients": [client_id],
    }
    if resource_server_id:
        auth_config["allowedScopes"] = [f"{resource_server_id}/gateway:read"]
    return auth_config


def resolve_auth_config(
    stack_name: Optional[str],
    cognito_config: Path,
    region: str,
) -> Optional[Dict[str, Any]]:
    if stack_name:
        return build_auth_from_stack(stack_name, region)
    if cognito_config.exists():
        return build_auth_from_cognito_config(cognito_config)
    return None


def sync_targets(targets_path: Path, region: str, account: str) -> None:
    default_target = {
        "name": "default",
        "description": "Default deployment target for AgentWatch",
        "account": account,
        "region": region,
    }

    targets = load_json(targets_path)
    if not isinstance(targets, list):
        raise ValueError(f"{targets_path} must contain a JSON array")

    for index, target in enumerate(targets):
        if target.get("name") == "default":
            targets[index] = default_target
            break
    else:
        targets.append(default_target)

    dump_json(targets_path, targets)


def sync_runtime_auth(
    agentcore_path: Path,
    runtime_name: str,
    auth_config: Optional[Dict[str, Any]],
) -> None:
    project = load_json(agentcore_path)
    runtimes = project.get("runtimes", [])
    if not runtimes:
        raise ValueError(f"{agentcore_path} does not define any runtimes")

    runtime = next((item for item in runtimes if item.get("name") == runtime_name), runtimes[0])

    if auth_config:
        runtime["authorizerType"] = "CUSTOM_JWT"
        runtime["authorizerConfiguration"] = {
            "customJwtAuthorizer": auth_config,
        }
    else:
        runtime.pop("authorizerType", None)
        runtime.pop("authorizerConfiguration", None)

    dump_json(agentcore_path, project)


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(project_root))
    parser.add_argument("--runtime-name", default="AgentWatch")
    parser.add_argument("--stack-name")
    parser.add_argument(
        "--cognito-config",
        default=str(project_root / "cognito_config.json"),
        help="Path to cognito_config.json from idp_setup/setup_cognito.py",
    )
    parser.add_argument(
        "--require-auth",
        action="store_true",
        help="Fail if no Cognito-based auth configuration can be resolved",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    agentcore_path = project_root / "agentcore" / "agentcore.json"
    targets_path = project_root / "agentcore" / "aws-targets.json"
    cognito_config = Path(args.cognito_config).resolve()

    region = get_session_region()
    account = get_account_id(region)

    sync_targets(targets_path, region, account)

    auth_config = resolve_auth_config(args.stack_name, cognito_config, region)
    if args.require_auth and auth_config is None:
        raise SystemExit(
            "No auth configuration found. Provide --stack-name or create cognito_config.json first."
        )

    sync_runtime_auth(agentcore_path, args.runtime_name, auth_config)

    print(f"Synchronized AgentCore config for account {account} in {region}")
    if auth_config:
        print(f"Configured CUSTOM_JWT authorizer for runtime {args.runtime_name}")
    else:
        print(f"No auth source found; runtime {args.runtime_name} left without authorizer config")


if __name__ == "__main__":
    main()
