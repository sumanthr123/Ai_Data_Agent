# Unity Catalog and workspace permissions checklist

The principle: the app reads shared data, writes only where uploads live, and calls only the model endpoints it
uses. Model-written SQL is read-only in code (`sql_guard.py`) regardless of grants; these grants are the second line.

Names below are this deployment's (`ai-data-agent`, catalog `ai_data_agent`). Replace them for another workspace.

## 1. App service principal (`app-2egxjy`, id `e572c2cb-a6ae-4943-9419-68439ce6dda5`)

| Securable | Privilege | Why | How it's granted | Status |
|---|---|---|---|---|
| SQL warehouse `3d46aa484790192c` | CAN USE | run queries | app resource `sql-warehouse` | ✅ |
| Catalog `ai_data_agent` | USE CATALOG | reach schemas | app resource / grant | ✅ |
| Schema `ai_data_agent.orders` | USE SCHEMA | reach shared tables | app resource | ✅ |
| Table `ai_data_agent.orders.superstore` | SELECT | rollback source | app resource `superstore-table` | ✅ |
| Schema `ai_data_agent.agent_gold` | USE SCHEMA, SELECT | answer questions | `data/` bundle grants | ✅ |
| Schema `ai_data_agent.gold`, table `gold.orders` | USE SCHEMA, SELECT | read `Last Refreshed` for freshness; `sql_guard` still refuses agent SQL here | bundle, `publish_agent_gold.py` | ✅ |
| Volume `ai_data_agent.orders.uploads` | READ VOLUME, WRITE VOLUME | stage uploaded files | app resources `uploads-volume`, `uploads-volume-read` | ✅ |
| Schema `ai_data_agent.user_uploads` | USE SCHEMA, CREATE TABLE, SELECT | create upload tables and the registry (the app then owns them) | direct grant, 2026-11-05 | ✅ |
| Serving endpoint `databricks-gpt-oss-120b` | CAN QUERY | Analyst, council member | app resource `gpt-oss-120b` | ✅ |
| Serving endpoint `databricks-llama-4-maverick` | CAN QUERY | Reviewer, council member | app resource `llama-4-maverick` | ⏳ re-add at next deploy |
| Serving endpoint `databricks-qwen35-122b-a10b` | CAN QUERY | Council judge (disputes only) | app resource `qwen35-122b` | ⏳ re-add at next deploy |
| Serving endpoint `gemini-3-5-flash` | CAN QUERY | Optional (out of Google credits since 2026-11-06) | app resource | ✅ |
| Serving endpoint `claude-sonnet-5-5` | CAN QUERY | Optional council member once credits exist | app resource | ✅ |
| Secret `ai_data_agent/gemini_api_key` | READ | web search in the classic chat | app resource `gemini-api-key` | ✅ |

Check: the app principal has **no** MODIFY, CREATE TABLE or ownership on `ai_data_agent.orders`, and no privileges on
any other catalog.

```sql
SHOW GRANTS `e572c2cb-a6ae-4943-9419-68439ce6dda5` ON SCHEMA ai_data_agent.orders;        -- USE SCHEMA only
SHOW GRANTS `e572c2cb-a6ae-4943-9419-68439ce6dda5` ON SCHEMA ai_data_agent.user_uploads;  -- USE SCHEMA, CREATE TABLE, SELECT
SHOW GRANTS `e572c2cb-a6ae-4943-9419-68439ce6dda5` ON TABLE ai_data_agent.orders.superstore;
```

### Changes

2026-11-05: `llama-3-3-70b`, `llama-4-maverick` and `qwen35-122b` were removed (unused then). 2026-11-06: Gemini ran
out of Google credits, so the roles moved to Databricks-hosted models; `llama-4-maverick` and `qwen35-122b` come back,
`llama-3-3-70b` stays removed. Changing an app's resources stops it and clears its deployment: run `databricks apps start` and
`databricks apps deploy` (same source path) afterwards.

## 2. Users of the app

| Mode | What users need |
|---|---|
| `USE_USER_TOKEN=false` (current) | CAN USE on the app only. Queries run as the app principal, and every answer says so (`auth.disclosure`). Uploads are isolated in code by the forwarded user identity. |
| `USE_USER_TOKEN=true` | Enable **user authorization** on the app with scopes `sql` and `catalog.tables:read` (plus `files.files` if users read volumes directly). Each user then needs USE CATALOG `ai_data_agent`, USE SCHEMA `orders`, SELECT on the shared tables, and CAN USE on the warehouse. Row filters and column masks on those tables then apply per user. For each upload, the app (as the table owner) grants SELECT on it to the uploader only. |

Switching to user tokens: enable user authorization in the app settings, grant the user privileges above (ideally to
a group), set `USE_USER_TOKEN=true` in `app.yaml`, and redeploy.

## 3. Data hygiene

- Upload tables are named `u_<user hash>_<id>`, owned by the app principal, and expire after `UPLOAD_TTL_HOURS` (24).
  A sweep drops expired tables and their volume folders, at most hourly and only while the app is in use (a timer
  would wake the warehouse when nobody is).
- `user_uploads.dataset_registry` is app-owned. Don't recreate it as a person; the app couldn't write to it.
- Raw files are kept under `/Volumes/ai_data_agent/orders/uploads/<user hash>/<conversation>/<upload id>/` until
  the upload expires or the user deletes it.
- Older files at the top of the `uploads` volume come from the classic chat's attachments and have no expiry yet.
