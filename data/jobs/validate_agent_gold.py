"""Fails the refresh, so the job emails its owner, when what the agent reads disagrees with gold.
Arguments: catalog, schema prefix."""
import sys

from pyspark.sql import SparkSession

catalog, prefix = sys.argv[1:3]
gold, agent = f"{catalog}.{prefix}gold.orders", f"{catalog}.{prefix}agent_gold"
spark = SparkSession.builder.getOrCreate()

g = spark.sql(f"""SELECT count(*) lines, count(DISTINCT row_id) ids, count(DISTINCT order_id) orders, sum(sales) sales, sum(profit) profit,
                  count_if(sales IS NULL OR profit IS NULL) missing FROM {gold}""").first()
v = spark.sql(f"SELECT count(*) lines, sum(sales) sales FROM {agent}.orders").first()
m = spark.sql(f"""SELECT MEASURE(total_sales) sales, MEASURE(total_profit) profit, MEASURE(order_count) orders,
                  MEASURE(profit_margin) margin FROM {agent}.sales_metrics""").first()

close = lambda a, b: abs(float(a or 0) - float(b or 0)) < 0.01  # noqa: E731
problems = [text for ok, text in [
    (g.lines > 0, "gold is empty"),
    (g.lines == g.ids, f"duplicate row_id: {g.lines} lines, {g.ids} ids"),
    (g.missing == 0, f"{g.missing} lines without sales or profit"),
    (v.lines == g.lines and close(v.sales, g.sales), f"lookup view differs from gold: {v.lines} lines, sales {v.sales} vs {g.sales}"),
    (close(m.sales, g.sales) and close(m.profit, g.profit), f"metric view differs from gold: sales {m.sales} vs {g.sales}, profit {m.profit} vs {g.profit}"),
    (m.orders == g.orders, f"order_count {m.orders} vs {g.orders}"),
    (abs(float(m.margin) - float(g.profit) / float(g.sales)) < 1e-6, f"profit_margin {m.margin}"),
] if not ok]
print(f"gold: {g.lines} lines, {g.orders} orders, sales {g.sales}, profit {g.profit}")
if problems:
    raise RuntimeError("; ".join(problems))
print("agent_gold matches gold")
