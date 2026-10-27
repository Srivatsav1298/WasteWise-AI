"""Optional scale-out path for very large deliveries.

Requires pyspark (``pip install -r requirements-spark.txt``). It is NOT part of
the default pipeline and it does NOT replace ``ingestion/silver.py``:

- it applies its own schema instead of the source contract, so it does not
  produce the same quarantine reasons;
- it does not write the warehouse tables the dbt models read.

Use it to pre-aggregate a delivery that is too large for the local runner, then
let the contract-enforcing path handle the result. The default pipeline is
``python scripts/run_end_to_end.py``.
"""
from pathlib import Path
from pyspark.sql import SparkSession, functions as F, types as T
ROOT=Path(__file__).resolve().parents[1]; RAW=str(ROOT/'data/raw'); CLEAN=str(ROOT/'data/clean')
SALES_SCHEMA=T.StructType([T.StructField('sale_id',T.StringType(),False),T.StructField('location_id',T.StringType(),False),T.StructField('sale_date',T.DateType(),False),T.StructField('product_id',T.StringType(),False),T.StructField('units_sold',T.DoubleType(),False)])
def clean_sales(spark):
    df=(spark.read.option('header',True).schema(SALES_SCHEMA).csv(f'{RAW}/sales.csv').filter((F.col('units_sold')>=0)&F.col('sale_id').isNotNull()).dropDuplicates(['sale_id']))
    df.write.mode('overwrite').partitionBy('sale_date').parquet(f'{CLEAN}/sales_parquet'); return df
def main():
    spark=SparkSession.builder.appName('wastewise-clean-operational-data').getOrCreate()
    try: print(f'clean sales rows={clean_sales(spark).count()}')
    finally: spark.stop()
if __name__=='__main__': main()
