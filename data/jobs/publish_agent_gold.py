"""Publish agent_gold: a lookup view and a metric view, each commented, with synonyms in the metric view's metadata."""
import sys

from pyspark.sql import SparkSession

catalog, prefix, app_principal = sys.argv[1:4]
gold, agent = f"{catalog}.{prefix}gold.orders", f"{catalog}.{prefix}agent_gold"
spark = SparkSession.builder.getOrCreate()

USD = "{type: currency, currency_code: USD, decimal_places: {type: exact, places: 2}}"
PERCENT = "{type: percentage, decimal_places: {type: exact, places: 1}}"
METRICS = f"""
version: 1.1
comment: Superstore sales measures at order-line grain. Query with MEASURE(); slice by the dimensions.
source: {gold}
dimensions:
  - {{name: order_date, expr: order_date, comment: Date the order was placed}}
  - {{name: order_month, expr: "DATE_TRUNC('MONTH', order_date)", comment: First day of the order month, synonyms: [month]}}
  - {{name: order_year, expr: YEAR(order_date), comment: Calendar year of the order, synonyms: [year]}}
  - {{name: region, expr: region, comment: "Central, East, South or West", synonyms: [sales region, area]}}
  - {{name: state, expr: state, comment: Shipping US state}}
  - {{name: city, expr: city, comment: Shipping city}}
  - {{name: segment, expr: segment, comment: "Consumer, Corporate or Home Office", synonyms: [customer segment]}}
  - {{name: category, expr: category, comment: Product category, synonyms: [product category]}}
  - {{name: sub_category, expr: sub_category, comment: Product sub-category, synonyms: [subcategory]}}
  - {{name: ship_mode, expr: ship_mode, comment: Shipping class, synonyms: [shipping method]}}
measures:
  - {{name: total_sales, expr: SUM(sales), comment: Revenue in USD after discount, synonyms: [revenue, turnover], format: {USD}}}
  - {{name: total_profit, expr: SUM(profit), comment: Profit in USD, synonyms: [earnings], format: {USD}}}
  - {{name: profit_margin, expr: "try_divide(SUM(profit), SUM(sales))", comment: Profit as a fraction of sales, synonyms: [margin], format: {PERCENT}}}
  - {{name: order_count, expr: COUNT(DISTINCT order_id), comment: "Distinct orders, not lines", synonyms: [orders, number of orders]}}
  - {{name: customer_count, expr: COUNT(DISTINCT customer_id), comment: Distinct customers, synonyms: [customers]}}
  - {{name: units_sold, expr: SUM(quantity), comment: Units sold, synonyms: [quantity, units]}}
  - {{name: avg_discount, expr: AVG(discount), comment: Mean discount per line as a fraction, synonyms: [average discount], format: {PERCENT}}}
"""

spark.sql(f"""CREATE OR REPLACE VIEW {agent}.orders
COMMENT 'Superstore order lines for lookups, one row per order line. Use sales_metrics for aggregates.'
AS SELECT * FROM {gold}""")
spark.sql(f"CREATE OR REPLACE VIEW {agent}.sales_metrics WITH METRICS LANGUAGE YAML AS $$\n{METRICS}\n$$")
spark.sql(f"SET TAG ON COLUMN {agent}.orders.customer_name pii = personal_name")
# Freshness reads Last Refreshed on gold. Granted here because the materialized view doesn't exist when the bundle deploys.
spark.sql(f"GRANT SELECT ON TABLE {gold} TO `{app_principal}`")
