#!/bin/bash

set -euo pipefail

# Prefer a globally installed modern AgentCore CLI when available.
if command -v agentcore >/dev/null 2>&1; then
    if agentcore --help 2>&1 | grep -q "Build and deploy Agentic AI applications on AgentCore"; then
        exec agentcore "$@"
    fi

    echo "Legacy AgentCore CLI detected; using @aws/agentcore via npx." >&2
fi

if ! command -v npx >/dev/null 2>&1; then
    echo "Error: npx is required to run the latest AgentCore CLI." >&2
    echo "Install Node.js 20+ and rerun this command." >&2
    exit 1
fi

exec npx -y @aws/agentcore "$@"
