"""Erase requested customers from every layer. Arguments: catalog, schema prefix, pipeline id, trace tables as table:col+col,...

Order matters: bronze first (else a replay restores them), then silver, then rebuild gold, then purge files.
Current data is clean when this finishes. Old table versions stay readable by time travel until their files pass the 7-day
retention, so every run purges, even with nothing pending; the weekly schedule completes each erasure.
The landing volume is the source of record and is purged separately. Do that BEFORE any full refresh of bronze: a full
refresh re-reads landing and would restore the person."""
import sys
import time

from databricks.sdk import WorkspaceClient
from pyspark.sql import SparkSession

catalog, prefix, pipeline_id = sys.argv[1:4]
traces = [t for t in (sys.argv[4] if len(sys.argv) > 4 else "").split(",") if t]
spark = SparkSession.builder.getOrCreate()
requests = f"{catalog}.{prefix}agent_ops.deletion_requests"
bronze, silver = f"{catalog}.{prefix}bronze.orders_raw", f"{catalog}.{prefix}silver.orders"


def purge() -> None:
    for table in (bronze, silver, *(t.split(":")[0] for t in traces)):
        spark.sql(f"REORG TABLE {table} APPLY (PURGE)")
        spark.sql(f"VACUUM {table} RETAIN 168 HOURS")


spark.sql(f"""CREATE TABLE IF NOT EXISTS {requests} (customer_id STRING NOT NULL, requested_at TIMESTAMP, completed_at TIMESTAMP)
COMMENT 'Erasure requests. Holds ids only.' CLUSTER BY AUTO""")
pending = [r.customer_id for r in spark.sql(f"SELECT DISTINCT customer_id FROM {requests} WHERE completed_at IS NULL LIMIT 1000").collect()]


def erase() -> None:
    args = {f"c{i}": c for i, c in enumerate(pending)}
    ids = ", ".join(f":{k}" for k in args)
    names = [r.customer_name for r in spark.sql(f"SELECT DISTINCT customer_name FROM {silver} WHERE customer_id IN ({ids})", args=args).collect() if r.customer_name]

    for table in (bronze, silver):
        spark.sql(f"DELETE FROM {table} WHERE customer_id IN ({ids})", args=args)

    w = WorkspaceClient()
    update = w.pipelines.start_update(pipeline_id, full_refresh_selection=[f"{catalog}.{prefix}gold.orders"]).update_id
    while (state := w.pipelines.get_update(pipeline_id, update).update.state.value) not in ("COMPLETED", "FAILED", "CANCELED"):
        time.sleep(10)
    if state != "COMPLETED":
        raise RuntimeError(f"gold rebuild {state}; requests stay pending and this job is safe to rerun")

    for spec in traces:  # traces hold free text, so match the person's id and name
        table, cols = spec.split(":")
        terms = {**args, **{f"n{i}": n for i, n in enumerate(names)}}
        match = " OR ".join(f"contains({c}, :{k})" for c in cols.split("+") for k in terms)
        spark.sql(f"DELETE FROM {table} WHERE {match}", args=terms)

    spark.sql(f"UPDATE {requests} SET completed_at = current_timestamp() WHERE completed_at IS NULL AND customer_id IN ({ids})", args=args)


if pending:  # no sys.exit here: serverless reports it as a failed run
    erase()
purge()
print(f"erased {len(pending)} subject(s); files past retention purged")
