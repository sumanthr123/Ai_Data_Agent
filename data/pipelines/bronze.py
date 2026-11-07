"""Bronze: raw feeds, append-only, all strings. Snapshots are CSV files; changes are JSON events with op and event_ts."""
from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

CATALOG, PREFIX, LANDING = (spark.conf.get(k) for k in ("agent.catalog", "agent.prefix", "agent.landing"))  # noqa: F821
TABLE = f"{CATALOG}.{PREFIX}bronze.orders_raw"
COLUMNS = ["row_id", "order_id", "order_date", "ship_date", "ship_mode", "customer_id", "customer_name", "segment", "country", "city", "state",
           "postal_code", "region", "product_id", "category", "sub_category", "product_name", "sales", "quantity", "discount", "profit"]

dp.create_streaming_table(TABLE, cluster_by_auto=True, comment="Superstore order lines as received, one row per feed record. Append-only.")


def _shape(df, op, event_ts):
    return df.select(*COLUMNS, F.expr(op).alias("op"), F.expr(event_ts).alias("event_ts"),
                     F.col("_metadata.file_path").alias("source_file"), F.current_timestamp().alias("ingested_at"))


@dp.append_flow(target=TABLE)
def snapshots():
    df = (spark.readStream.format("cloudFiles").option("cloudFiles.format", "csv")  # noqa: F821
          .option("header", "true").option("escape", '"').option("multiLine", "true")
          .option("cloudFiles.inferColumnTypes", "false")
          .option("cloudFiles.schemaEvolutionMode", "rescue")
          .load(f"{LANDING}/snapshots/"))
    named = {c.lower().replace(" ", "_").replace("-", "_"): c for c in df.columns}
    df = df.select(*[F.col(f"`{named[c]}`").alias(c) for c in COLUMNS], "_metadata")
    return _shape(df, "'U'", "CAST(_metadata.file_modification_time AS STRING)")


@dp.append_flow(target=TABLE)
def changes():
    schema = StructType([StructField(c, StringType()) for c in [*COLUMNS, "op", "event_ts"]])
    df = (spark.readStream.format("cloudFiles").option("cloudFiles.format", "json")  # noqa: F821
          .option("cloudFiles.schemaEvolutionMode", "rescue").schema(schema).load(f"{LANDING}/changes/"))
    return _shape(df, "op", "event_ts")
