# Minimal image for MCP inspectors/registries (e.g. Glama) and anyone who wants
# the server containerised. The MCP speaks stdio: run interactively (-i).
#
#   docker build -t sportsdata-mcp .
#   docker run -i --rm sportsdata-mcp
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .
# Free by default: with no config, the full catalogue serves (see config.py).
ENTRYPOINT ["sportsdata-mcp", "serve"]
