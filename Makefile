DIR := $(shell pwd)

.PHONY: install init-env check claude-config

install:
	uv sync

# Create .env from template with MCP1_SERVER_PATH pre-filled
init-env:
	@if [ -f .env ]; then \
		echo ".env already exists"; \
	else \
		sed 's|MCP1_SERVER_PATH=.*|MCP1_SERVER_PATH=$(DIR)/src/mcp1_vectorstore/server.py|' .env.example > .env; \
		echo "Created .env — fill in your Azure credentials"; \
	fi

# Verify .env is present and both settings classes load without error
check:
	@test -f .env || (echo "ERROR: .env not found — run 'make init-env' first" && exit 1)
	@uv run python -c "import sys; sys.path.insert(0, 'src'); from mcp1_vectorstore.settings import Settings; Settings(); print('MCP1 OK')"
	@uv run python -c "import sys; sys.path.insert(0, 'src'); from mcp2_orchestrator.settings import Settings; Settings(); print('MCP2 OK')"

# Print the block to paste into %APPDATA%\Claude\claude_desktop_config.json
claude-config:
	@echo '{'
	@echo '  "mcpServers": {'
	@echo '    "acme-orchestrator": {'
	@echo '      "command": "wsl",'
	@echo '      "args": ["bash", "-lc", "cd $(DIR) && uv run python src/mcp2_orchestrator/server.py"]'
	@echo '    }'
	@echo '  }'
	@echo '}'
