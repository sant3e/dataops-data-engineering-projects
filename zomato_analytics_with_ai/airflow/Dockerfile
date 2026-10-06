# Airflow 3.x image + Snowflake provider + FAB auth + dbt venv + openai (for local Ollama LLM endpoint).
FROM apache/airflow:3.0.3

# Providers & Client Libraries: snowflake, fab auth, openai client for Ollama endpoint
RUN pip install --no-cache-dir \
      apache-airflow-providers-snowflake \
      apache-airflow-providers-fab \
      openai

# dbt in its own venv so it never clashes with Airflow's deps. DAG calls /opt/airflow/dbt_venv/bin/dbt
RUN python -m venv /opt/airflow/dbt_venv && \
    /opt/airflow/dbt_venv/bin/pip install --no-cache-dir "dbt-snowflake==1.8.*"
