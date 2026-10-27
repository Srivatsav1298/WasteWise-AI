# Airflow with the WasteWiseAI pipeline dependencies.
#
#   docker build -f airflow/Dockerfile -t wastewise-airflow .
#   docker compose -f airflow/docker-compose.yml up
#
# The image is the stock Airflow image plus DuckDB and dbt, because the DAG
# runs the same pipeline scripts the local runner runs.
FROM apache/airflow:3.0.2

USER root
RUN apt-get update \
    && apt-get install --no-install-recommends -y gcc python3-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
USER airflow

COPY requirements.txt /opt/wastewise/requirements.txt
RUN pip install --no-cache-dir -r /opt/wastewise/requirements.txt
