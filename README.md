# Consensus AI Data Agent

Databricks App that answers questions about `ai_data_agent.orders.superstore` data, live web and general topics by asking a council of models (Gemini, GPT-OSS, Claude) in parallel, checking their SQL results against each other and the question, and writing a cited answer.

## Quick start
```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
MOCK_MODE=true uvicorn app:app --port 8000        # demo mode, no workspace calls
DATABRICKS_CONFIG_PROFILE=<profile> MOCK_MODE=false uvicorn app:app --port 8000   # live
```

## Deploy
```bash
databricks workspace import-dir . /Workspace/Users/<you>/consensus-agent-src --overwrite
databricks apps deploy ai-data-agent --source-code-path /Workspace/Users/<you>/consensus-agent-src
```
Secrets: store the Gemini key as the Databricks secret referenced in `app.yaml`; never commit keys.

See `CLAUDE.md` for architecture, tests and rules.
