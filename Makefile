DIR     := $(shell pwd)
CERT    := $(DIR)/certs/cert.pem
KEY     := $(DIR)/certs/key.pem

.PHONY: install init-env check setup-cert run-mcp1 run-mcp2 run-all claude-config pack

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

# Generate a localhost cert with mkcert and install its root CA into Windows (Electron-compatible)
# Run once: sudo apt install mkcert  (if not already installed)
setup-cert:
	@mkdir -p $(DIR)/certs
	@which mkcert > /dev/null 2>&1 || (echo "ERROR: mkcert not found — run: sudo apt install mkcert" && exit 1)
	mkcert -cert-file $(CERT) -key-file $(KEY) localhost 127.0.0.1
	cp "$$(mkcert -CAROOT)/rootCA.pem" /mnt/c/Windows/Temp/mkcert-root.pem
	cmd.exe /c "certutil -addstore -f ROOT C:\\Windows\\Temp\\mkcert-root.pem"
	rm /mnt/c/Windows/Temp/mkcert-root.pem
	@echo ""
	@echo "Done. Restart Claude Desktop."

# Start MCP 1 vector store server (HTTP on port 8001 — internal only)
run-mcp1:
	uv run uvicorn mcp1_vectorstore.server:app --host 0.0.0.0 --port 8001 --app-dir src

# Start MCP 2 orchestrator server (HTTP on port 8002)
run-mcp2:
	uv run uvicorn mcp2_orchestrator.server:app --host 0.0.0.0 --port 8002 --app-dir src

# Bundle Python deps into dxt/lib/ and pack into a .mcpb file
# Prerequisites: npm install -g @anthropic-ai/mcpb
pack:
	uv pip install --target dxt/lib mcp httpx anyio
	npx @anthropic-ai/mcpb pack dxt/ acme-orchestrator-proxy.mcpb
	@echo ""
	@echo "Double-click acme-orchestrator-proxy.mcpb in Windows Explorer to install."

# Print the Claude Desktop config block (stdio proxy → MCP2 over HTTP)
claude-config:
	@echo 'Paste into %APPDATA%\Claude\claude_desktop_config.json:'
	@echo '{'
	@echo '  "mcpServers": {'
	@echo '    "acme-orchestrator": {'
	@echo '      "command": "wsl",'
	@echo '      "args": ["-e", "bash", "-c", "cd $(DIR) && /home/bbarnett/.local/bin/uv run python dxt/server/proxy.py"],'
	@echo '      "env": { "MCP2_URL": "http://127.0.0.1:8002" }'
	@echo '    }'
	@echo '  }'
	@echo '}'