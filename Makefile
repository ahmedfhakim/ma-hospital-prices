PY ?= python3
DBT = cd transform && dbt build --profiles-dir . --full-refresh

.PHONY: setup test demo discover ingest transform dashboard all clean

setup:            ## install dependencies into a virtualenv
	$(PY) -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

test:             ## parser tests against CMS's official example files
	$(PY) -m pytest -q

demo:             ## full pipeline on 3 fictional hospitals (no downloads, ~10s)
	$(PY) scripts/make_demo_data.py
	rm -rf data/demo/parquet
	for f in data/demo/files/*; do \
		id=$$(basename $${f%.*}); $(PY) -m ingest local $$f --id $$id --out data/demo/parquet || exit 1; \
	done
	$(DBT) --vars '{parquet_dir: ../data/demo/parquet}'
	$(PY) dashboard/build.py

discover:         ## print each hospital's price-file URL from its cms-hpt.txt
	$(PY) -m ingest discover

ingest:           ## download changed price files and parse them to Parquet
	$(PY) -m ingest run

transform:        ## dbt models + tests on the real data
	$(DBT)

dashboard:        ## bake the marts into dashboard/site/index.html
	$(PY) dashboard/build.py

all: ingest transform dashboard

clean:
	rm -rf data/parquet data/demo data/warehouse.duckdb transform/target transform/logs
