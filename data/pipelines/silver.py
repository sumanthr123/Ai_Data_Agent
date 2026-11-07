"""Silver: current state per order line. SCD1 so an erased person leaves no history; late and duplicate events resolve by event_ts."""
from pyspark import pipelines as dp
from pyspark.sql import functions as F

CATALOG, PREFIX = (spark.conf.get(k) for k in ("agent.catalog", "agent.prefix"))  # noqa: F821
BRONZE = f"{CATALOG}.{PREFIX}bronze.orders_raw"
TABLE = f"{CATALOG}.{PREFIX}silver.orders"
TEXT = ["order_id", "ship_mode", "customer_id", "customer_name", "segment", "country", "city", "state", "region", "product_id", "category",
        "sub_category", "product_name"]


def _date(c):
    # The file writes 11/8/16; the change feed writes 11/8/2016. yy must go first: M/d/yyyy would read 16 as the year 16.
    return F.expr(f"coalesce(try_to_date({c}, 'M/d/yy'), try_to_date({c}, 'M/d/yyyy'))").alias(c)


def clean(df):
    """ANSI-safe: a bad value becomes NULL and the expectations decide, rather than failing the whole update."""
    return df.select(
        F.expr("try_cast(row_id AS BIGINT)").alias("row_id"),
        *[F.trim(F.col(c)).alias(c) for c in TEXT],
        _date("order_date"),
        _date("ship_date"),
        F.lpad(F.col("postal_code"), 5, "0").alias("postal_code"),  # leading zeros are lost upstream
        F.expr("try_cast(sales AS DECIMAL(18,4))").alias("sales"),
        F.expr("try_cast(quantity AS INT)").alias("quantity"),
        F.expr("try_cast(discount AS DECIMAL(5,4))").alias("discount"),
        F.expr("try_cast(profit AS DECIMAL(18,4))").alias("profit"),
        F.upper(F.col("op")).alias("op"),
        F.expr("try_to_timestamp(event_ts)").alias("event_ts"),
    )


@dp.temporary_view(name="orders_changes")
@dp.expect_all_or_drop({"event_ts_present": "event_ts IS NOT NULL", "key_present": "row_id IS NOT NULL", "op_known": "op IN ('U', 'D')"})
def orders_changes():
    # skipChangeCommits: GDPR deletes in bronze must not fail this stream.
    return clean(spark.readStream.option("skipChangeCommits", "true").table(BRONZE))  # noqa: F821


dp.create_streaming_table(TABLE, cluster_by_auto=True, comment="Superstore order lines, current state. SCD1.")
dp.create_auto_cdc_flow(target=TABLE, source="orders_changes", keys=["row_id"], sequence_by=F.col("event_ts"),
                        apply_as_deletes=F.expr("op = 'D'"), except_column_list=["op", "event_ts"], stored_as_scd_type=1)
