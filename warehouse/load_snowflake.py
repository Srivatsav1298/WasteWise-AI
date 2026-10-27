"""Snowflake loader skeleton. Uses environment credentials and explicit COPY targets."""
import os
from pathlib import Path

def load():
    try:
        import snowflake.connector
    except ImportError as exc:
        raise SystemExit('Install snowflake-connector-python before using this loader') from exc
    required=['SNOWFLAKE_ACCOUNT','SNOWFLAKE_USER','SNOWFLAKE_PASSWORD']
    missing=[name for name in required if not os.getenv(name)]
    if missing: raise SystemExit(f'Missing environment variables: {", ".join(missing)}')
    conn=snowflake.connector.connect(account=os.environ['SNOWFLAKE_ACCOUNT'], user=os.environ['SNOWFLAKE_USER'], password=os.environ['SNOWFLAKE_PASSWORD'], database=os.getenv('SNOWFLAKE_DATABASE','WASTEWISE'), schema='RAW', warehouse=os.getenv('SNOWFLAKE_WAREHOUSE','WASTEWISE_XS'), role=os.getenv('SNOWFLAKE_ROLE'))
    try:
        root=Path(__file__).resolve().parents[1]
        with conn.cursor() as cur:
            cur.execute('create stage if not exists WASTEWISE.RAW.LOCAL_STAGE')
            for name, table in [('sales.csv','SALES'),('inventory_snapshots.csv','INVENTORY_SNAPSHOTS'),('waste_events.csv','WASTE_EVENTS'),('events.csv','EVENTS')]:
                cur.execute(f"put file://{(root/'data/clean'/name).resolve()} @WASTEWISE.RAW.LOCAL_STAGE auto_compress=true overwrite=true")
                cur.execute(f"-- COPY INTO WASTEWISE.RAW.{table} should be reviewed with the table-specific file format before production")
    finally: conn.close()
if __name__=='__main__': load()
