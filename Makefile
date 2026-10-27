PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

.PHONY: help install generate pipeline publish serve test test-frontend test-a11y test-blocked test-airflow airflow-up airflow-down check dbt-build clean

help:
	@echo "make install       install python and node dependencies"
	@echo "make generate      regenerate the synthetic delivery files"
	@echo "make pipeline      run the full pipeline (deliveries to published artefacts)"
	@echo "make publish       run only the trust engine and the export"
	@echo "make dbt-build     rebuild the warehouse models with dbt"
	@echo "make test          run the python test suite"
	@echo "make test-frontend run the browser smoke test on the dashboard"
	@echo "make test-a11y     run the accessibility and contrast audit"
	@echo "make test-blocked  prove a blocked gate shows no stale numbers"
	@echo "make test-airflow  check the Airflow DAG contract without Airflow installed"
	@echo "make airflow-up    start Airflow with the WasteWiseAI DAG (docker compose)"
	@echo "make check         syntax check every python and javascript file"
	@echo "make serve         serve the dashboard on http://localhost:4173"
	@echo "make clean         remove derived data, the warehouse, logs and build artefacts"

install:
	$(PIP) install -r requirements.txt
	npm install

generate:
	$(PYTHON) ingestion/generate_synthetic.py

pipeline:
	$(PYTHON) scripts/run_end_to_end.py

publish:
	$(PYTHON) scripts/trust_engine.py
	$(PYTHON) scripts/export_marts.py

dbt-build:
	cd dbt_project && dbt build --profiles-dir .

test:
	$(PYTHON) -m unittest discover -s tests -v

test-frontend:
	node tests/frontend_smoke.mjs

test-a11y:
	node tests/frontend_a11y.mjs

test-blocked:
	node tests/frontend_blocked.mjs

test-airflow:
	$(PYTHON) -m unittest tests.test_airflow_dag -v

airflow-up:
	docker compose -f airflow/docker-compose.yml up --build

airflow-down:
	docker compose -f airflow/docker-compose.yml down

check:
	node --check data.js
	node --check charts.js
	node --check views.js
	node --check views-ops.js
	node --check app.js
	$(PYTHON) -m py_compile ingestion/*.py scripts/*.py orchestration/*.py warehouse/*.py pyspark_jobs/*.py airflow/dags/*.py

serve:
	$(PYTHON) -m http.server 4173

clean:
	rm -rf data/bronze data/silver data/clean data/quarantine data/marts data/legacy
	rm -f data/warehouse.duckdb
	rm -rf dbt_project/target dbt_project/logs logs
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
