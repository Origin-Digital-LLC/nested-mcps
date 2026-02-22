DIR := $(shell pwd)

.PHONY: install init-env check run-mcp1 run-mcp2 claude-config pack

install:
	uv sync

# Create .env from template
init-env:
	@if [ -f .env ]; then \
		echo ".env already exists"; \
	else \
		cp .env.example .env; \
		echo "Created .env — fill in your Azure credentials"; \
	fi

# Verify .env is present and both settings classes load without error
check:
	@test -f .env || (echo "ERROR: .env not found — run 'make init-env' first" && exit 1)
	@uv run python -c "import sys; sys.path.insert(0, 'src'); from mcp1_vectorstore.settings import Settings; Settings(); print('MCP1 OK')"
	@uv run python -c "import sys; sys.path.insert(0, 'src'); from mcp2_orchestrator.settings import Settings; Settings(); print('MCP2 OK')"

# Start MCP 1 vector store server (HTTP on port 8001 — internal only)
run-mcp1:
	uv run uvicorn mcp1_vectorstore.server:app --host 0.0.0.0 --port 8001 --app-dir src

# Start MCP 2 orchestrator server (HTTP on port 8002)
run-mcp2:
	uv run uvicorn mcp2_orchestrator.server:app --host 0.0.0.0 --port 8002 --app-dir src

# Bundle Python deps into extension/lib/ and pack into a .mcpb file
pack:
	uv pip install --target extension/lib mcp httpx anyio
	npx @anthropic-ai/mcpb pack extension/ acme-orchestrator-proxy.mcpb
	@echo ""
	@echo "Double-click acme-orchestrator-proxy.mcpb in Windows Explorer to install."

# Print the Claude Desktop config block for local dev (stdio proxy → MCP2 over HTTP)
claude-config:
	@echo 'Paste into %APPDATA%\Claude\claude_desktop_config.json:'
	@echo '{'
	@echo '  "mcpServers": {'
	@echo '    "acme-orchestrator": {'
	@echo '      "command": "wsl",'
	@echo '      "args": ["-e", "bash", "-c", "cd $(DIR) && /home/bbarnett/.local/bin/uv run python extension/server/proxy.py"],'
	@echo '      "env": { "MCP2_URL": "http://127.0.0.1:8002" }'
	@echo '    }'
	@echo '  }'
	@echo '}'