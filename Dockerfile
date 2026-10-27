# WasteWiseAI: one image that builds the warehouse and serves the dashboard.
#
#   docker build -t wastewiseai .
#   docker run --rm -p 4173:4173 wastewiseai
#
# The container runs the pipeline on start, so the artefacts the dashboard reads
# are always produced by the same image that serves them. Pass
# WASTEWISE_SKIP_PIPELINE=1 to serve pre-built artefacts instead.
FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip && pip install -r requirements.txt

COPY ingestion ./ingestion
COPY scripts ./scripts
COPY orchestration ./orchestration
COPY dbt_project ./dbt_project
COPY data ./data
COPY index.html styles.css data.js charts.js views.js views-ops.js app.js ./

RUN useradd --create-home --uid 10001 wastewise \
    && chown -R wastewise:wastewise /app
USER wastewise

EXPOSE 4173

CMD ["sh", "-c", "if [ \"$WASTEWISE_SKIP_PIPELINE\" != \"1\" ]; then python scripts/run_end_to_end.py; fi && exec python -m http.server 4173 --bind 0.0.0.0"]
