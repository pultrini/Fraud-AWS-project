FROM apache/superset:6.1.0

USER root

RUN uv pip install \
    --no-cache-dir \
    duckdb==1.5.5 \
    duckdb-engine

USER superset
