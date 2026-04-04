#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
AGENTCORE_CLI="$SCRIPT_DIR/agentcore_cli.sh"
SYNC_SCRIPT="$SCRIPT_DIR/sync_agentcore_config.py"
RUNTIME_NAME="AgentWatch"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

WAIT_FOR_READY=false
STACK_NAME=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --wait)
            WAIT_FOR_READY=true
            shift
            ;;
        --stack-name)
            STACK_NAME="${2:-}"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [--wait] [--stack-name <name>]"
            echo ""
            echo "Options:"
            echo "  --wait               Wait for the deployed runtime to report READY"
            echo "  --stack-name <name>  Read Cognito auth settings from a CloudFormation stack"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  AgentCore Runtime Deployment${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

if [ ! -d "$PROJECT_ROOT/agentcore" ]; then
    echo -e "${RED}Error: agentcore/ project config not found${NC}"
    exit 1
fi

if [ ! -x "$AGENTCORE_CLI" ]; then
    echo -e "${RED}Error: AgentCore CLI wrapper is not executable: $AGENTCORE_CLI${NC}"
    exit 1
fi

echo -e "${YELLOW}Synchronizing AgentCore config...${NC}"
SYNC_ARGS=(--project-root "$PROJECT_ROOT")
if [ -n "$STACK_NAME" ]; then
    SYNC_ARGS+=(--stack-name "$STACK_NAME")
fi
python3 "$SYNC_SCRIPT" "${SYNC_ARGS[@]}"

echo ""
echo -e "${YELLOW}Validating AgentCore project...${NC}"
(cd "$PROJECT_ROOT" && "$AGENTCORE_CLI" validate)

echo ""
echo -e "${YELLOW}Installing CDK dependencies...${NC}"
(cd "$PROJECT_ROOT/agentcore/cdk" && npm ci)

echo ""
echo -e "${YELLOW}Deploying runtime...${NC}"
(cd "$PROJECT_ROOT" && "$AGENTCORE_CLI" deploy -y)

echo ""
echo -e "${YELLOW}Fetching deployed access details...${NC}"
(cd "$PROJECT_ROOT" && "$AGENTCORE_CLI" fetch access --type agent --name "$RUNTIME_NAME" || true)

if [ "$WAIT_FOR_READY" = true ]; then
    echo ""
    echo -e "${YELLOW}Waiting for runtime to report READY...${NC}"
    ATTEMPTS=60
    for ((i=1; i<=ATTEMPTS; i++)); do
        STATUS_JSON=$(cd "$PROJECT_ROOT" && "$AGENTCORE_CLI" status --runtime "$RUNTIME_NAME" --json 2>/dev/null || true)
STATE=$(python3 - <<'PY' "$STATUS_JSON"
import json
import re
import sys

raw = sys.argv[1]
if not raw:
    print("")
    raise SystemExit(0)

try:
    cleaned = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", raw).strip()
    json_start = min(
        [idx for idx in (cleaned.find("{"), cleaned.find("[")) if idx != -1],
        default=-1,
    )
    if json_start == -1:
        print("")
        raise SystemExit(0)

    cleaned = cleaned[json_start:]
    if cleaned.startswith("{"):
        json_end = cleaned.rfind("}")
    else:
        json_end = cleaned.rfind("]")

    if json_end == -1:
        print("")
        raise SystemExit(0)

    payload = json.loads(cleaned[: json_end + 1])
except json.JSONDecodeError:
    print("")
    raise SystemExit(0)

items = []
if isinstance(payload, list):
    items = payload
elif isinstance(payload, dict):
    if isinstance(payload.get("items"), list):
        items = payload["items"]
    elif isinstance(payload.get("resources"), list):
        items = payload["resources"]
    else:
        items = [payload]

for item in items:
    if isinstance(item, dict):
        state = (
            item.get("status")
            or item.get("state")
            or item.get("detail")
            or item.get("deploymentState")
        )
        if state:
            print(state)
            raise SystemExit(0)
print("")
PY
)

        if [ "$STATE" = "READY" ] || [ "$STATE" = "deployed" ]; then
            echo -e "${GREEN}Runtime is ready.${NC}"
            break
        fi

        if [ "$i" -eq "$ATTEMPTS" ]; then
            echo -e "${YELLOW}Timed out waiting for READY state. Check status manually.${NC}"
            break
        fi

        sleep 10
    done
fi

echo ""
echo -e "${GREEN}Deployment flow completed.${NC}"
