"""Gold: the business table. A bad row stops the update here, so the agent keeps reading the last good version."""
from pyspark import pipelines as dp

CATALOG, PREFIX = (spark.conf.get(k) for k in ("agent.catalog", "agent.prefix"))  # noqa: F821

SCHEMA = """
  row_id BIGINT NOT NULL COMMENT 'Unique line id. Each row is one product on one order.',
  order_id STRING COMMENT 'Order id; an order has one or more lines, so count DISTINCT order_id for orders.',
  order_date DATE COMMENT 'Date the order was placed.',
  ship_date DATE COMMENT 'Date the order shipped.',
  ship_mode STRING COMMENT 'Standard Class, Second Class, First Class or Same Day.',
  customer_id STRING COMMENT 'Customer id.',
  customer_name STRING COMMENT 'Customer full name. Personal data.',
  segment STRING COMMENT 'Consumer, Corporate or Home Office.',
  country STRING COMMENT 'Shipping country.',
  city STRING COMMENT 'Shipping city.',
  state STRING COMMENT 'Shipping US state.',
  postal_code STRING COMMENT 'US ZIP code, five digits.',
  region STRING COMMENT 'Central, East, South or West.',
  product_id STRING COMMENT 'Product id.',
  category STRING COMMENT 'Furniture, Office Supplies or Technology.',
  sub_category STRING COMMENT 'Product sub-category such as Chairs or Phones.',
  product_name STRING COMMENT 'Product name.',
  sales DECIMAL(18,4) COMMENT 'Line revenue in USD after discount.',
  quantity INT COMMENT 'Units on the line.',
  discount DECIMAL(5,4) COMMENT 'Discount as a fraction; 0.2 is 20 percent.',
  profit DECIMAL(18,4) COMMENT 'Line profit in USD; negative is a loss.'
"""
NAMES = [line.split()[0] for line in SCHEMA.strip().splitlines()]


@dp.materialized_view(name=f"{CATALOG}.{PREFIX}gold.orders", schema=SCHEMA, cluster_by_auto=True, comment="Superstore retail sales, one row per order line.")
@dp.expect_or_fail("row_id_present", "row_id IS NOT NULL")
@dp.expect_or_fail("order_date_present", "order_date IS NOT NULL")
@dp.expect_or_fail("quantity_positive", "quantity > 0")
def orders():
    return spark.read.table(f"{CATALOG}.{PREFIX}silver.orders").select(*NAMES)  # noqa: F821
