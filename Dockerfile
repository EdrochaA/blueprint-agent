FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_NO_PROGRESS=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1 \
    DOCKER_CONTAINER=1 \
    AWS_REGION=eu-west-1 \
    AWS_DEFAULT_REGION=eu-west-1 \
    OTEL_PYTHON_DISABLED_INSTRUMENTATIONS=threading \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml ./
RUN uv sync --no-dev --no-cache

# Copy the agent code
COPY agent/ agent/

# Create non-root user
RUN useradd -m -u 1000 bedrock_agentcore && \
    chown -R bedrock_agentcore:bedrock_agentcore /app
USER bedrock_agentcore

# AgentCore Runtime expects /invocations (POST) and /ping (GET) on port 8080
EXPOSE 8080

# Use the full module path
CMD ["opentelemetry-instrument", "python", "-m", "agent.main"]
