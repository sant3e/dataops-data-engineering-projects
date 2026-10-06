# Runbook — run the Zomato AI Data Engineering project

Step-by-step guide to build and run the whole project. For what each layer is and why it is built that way, read the [README](../README.md).

You install only three things on your machine: **Docker**, **Ollama**, and (for the dataset upload) the **AWS CLI or the S3 console**. Airflow, dbt, Python and the Streamlit apps all run inside the Docker container. You do not need Python or dbt on your machine.

**Order of work:** 1. Cloud setup → 2. Local LLM → 3. Docker → 4. Run and test → 5. Stop and reset.

> Run every `docker compose` command from the `airflow/` folder. `docker compose` looks for `docker-compose.yaml` in the current folder. If you see `no configuration file provided: not found`, you are in the wrong folder.

---

## 1 · Cloud setup (S3, AWS IAM, Snowflake)

You need an AWS account, a Snowflake account (a trial is enough) and a Snowsight login with the `ACCOUNTADMIN` role.

### 1.1 Get the data into S3

1. Download the CSV files into `data/`. The download link is in the [README](../README.md).
2. Create an S3 bucket, for example `zomato-dl-<yourname>`.
3. Upload each CSV to its own folder: `raw/restaurants/`, `raw/users/`, `raw/food/`, `raw/menu/`, `raw/orders/`, `raw/order_items/`, `raw/reviews/`.

### 1.2 Create the AWS policy and role

Use the JSON files in [`aws/iam/`](../aws/iam/). Replace `<BUCKET>` and `<ACCOUNT_ID>` first.

1. Create the IAM policy `zomato-s3-read` from `s3-read-policy.json`.
2. Create the IAM role `snowflake-zomato-role`. Use `snowflake-role-trust-policy-initial.json` as the trust policy, and attach the policy `zomato-s3-read`.
3. Copy the role ARN: `arn:aws:iam::<ACCOUNT_ID>:role/snowflake-zomato-role`.

### 1.3 Create the Snowflake objects

In Snowsight, run the scripts in [`snowflake/`](../snowflake/) in this order, as `ACCOUNTADMIN`:

| Step | Script | You must edit |
|---|---|---|
| 1 | `01_setup.sql` | nothing |
| 2 | `02_storage_integration.sql` | `<ROLE_ARN>` and `<BUCKET>` |
| 3 | Run `DESC INTEGRATION ZOMATO_S3_INT;` | copy `STORAGE_AWS_IAM_USER_ARN` and `STORAGE_AWS_EXTERNAL_ID` |
| 4 | In AWS, edit the role trust policy | use `snowflake-role-trust-policy-final.json` with the two values from step 3 |
| 5 | `03_stage_and_formats.sql` | `<BUCKET>` |
| 6 | `04_raw_tables.sql` | nothing |
| 7 | `05_copy_into.sql` | nothing (optional, see below) |

- Do not run `02_storage_integration.sql` again after step 4. The [README](../README.md#2--s3--snowflake-one-keyless-handshake) explains why.
- Step 7 is optional. The Airflow DAG runs the same `COPY INTO` commands.
- `01_setup.sql` gives the role `DBT_ROLE` to the user that runs it. Use the same Snowflake user in the Docker `.env` file (section 3.2).

**Check:** `LIST @ZOMATO.RAW.ZOMATO_RAW_STAGE;` shows the seven table folders.

---

## 2 · Local LLM (Ollama)

The project uses a local model, so no API key or cloud LLM account is needed. The model is `qwen2.5-coder:14b`. It needs about 9 GB of disk and about 16 GB of RAM.

### 2.1 Install Ollama

- **macOS:** `brew install ollama`, or download the app from <https://ollama.com/download>.
- **Windows:** download the installer from <https://ollama.com/download>.
- **Linux:** `curl -fsSL https://ollama.com/install.sh | sh`

### 2.2 Download the model

```bash
ollama pull qwen2.5-coder:14b
```

### 2.3 Start the server

```bash
ollama serve
```

If you installed the macOS or Windows app, the server already runs in the background. In that case `ollama serve` reports that the port is in use. This is normal.

### 2.4 Check that it works

```bash
curl http://localhost:11434/api/tags      # the model appears in the list
ollama run qwen2.5-coder:14b "Say hello"  # type /bye to exit
```

The containers reach Ollama at `http://host.docker.internal:11434/v1`. This value is the default in `docker-compose.yaml`. You do not need to change it on macOS or Windows.

> **Linux:** `host.docker.internal` does not exist by default. Add `extra_hosts: ["host.docker.internal:host-gateway"]` to the `x-airflow-common` block in `airflow/docker-compose.yaml`.

---

## 3 · Docker

### 3.1 Install

- Install **Docker Desktop** from <https://www.docker.com/products/docker-desktop/>. It includes Docker Compose v2.
- In Docker Desktop settings, give Docker at least **6 GB of memory**. The sentence-transformers library and Airflow need it.
- Check: `docker --version` and `docker compose version`.

### 3.2 Configure credentials

```bash
cd airflow
cp example.env .env
```

Edit `airflow/.env`:

| Variable | Value |
|---|---|
| `SNOWFLAKE_ACCOUNT` | your account identifier, for example `ORGNAME-ACCOUNTNAME` |
| `SNOWFLAKE_USER` | the Snowflake user from step 1.3 |
| `SNOWFLAKE_PASSWORD` | the password of that user |
| `OLLAMA_BASE_URL` | keep `http://host.docker.internal:11434/v1` |
| `OLLAMA_MODEL` | keep `qwen2.5-coder:14b` |
| `SAMPLE_N` | number of reviews to enrich in each DAG run (default `5`) |

The `.env` file is ignored by git. Never commit it.

### 3.3 Build and start

```bash
docker compose build           # first build takes several minutes
docker compose up -d
docker compose ps              # wait until apiserver, scheduler and dag-processor are running
```

The `airflow-init` container runs once and then exits. This is normal.

### 3.4 Operate

| Task | Command |
|---|---|
| Airflow UI | <http://localhost:8080> (user `admin`, password `admin`) |
| See container status | `docker compose ps` |
| Follow logs | `docker compose logs -f scheduler` |
| Open a shell in the container | `docker compose exec scheduler bash` |
| Restart after a code or `.env` change | `docker compose up -d` |
| Rebuild after a `Dockerfile` change | `docker compose build && docker compose up -d` |

The `dags/`, `zomato/` and `ai/` folders are mounted into the container. A change to a file in these folders is visible in the container at once, without a rebuild.

---

## 4 · Run and test everything (from the container)

Run all commands in this section from the `airflow/` folder. Make sure that Ollama runs (section 2) and the containers run (section 3).

### 4.1 The Airflow DAG

The DAG `zomato_batch` runs the whole pipeline: `reload_raw` → `dbt_build_core` → `enrich_reviews` → `dbt_build_ai`.

**With the UI:** open <http://localhost:8080>, turn on the toggle for `zomato_batch`, then click the **Trigger** button.

**With the CLI:**
```bash
docker compose exec scheduler airflow dags unpause zomato_batch
docker compose exec scheduler airflow dags trigger zomato_batch
```

**Expected result:** all four tasks are green. The first run takes a long time, because dbt builds 10M orders.

**Check in Snowsight:**
```sql
USE ROLE DBT_ROLE; USE WAREHOUSE ZOMATO_WH;
SELECT COUNT(*) FROM ZOMATO.RAW.ORDERS;                       -- 10,000,000
SELECT COUNT(*) FROM ZOMATO.MARTS.FCT_ORDERS;                 -- 10,000,000
SELECT * FROM ZOMATO.MARTS.MART_DAILY_CITY_REVENUE LIMIT 10;
SELECT COUNT(*) FROM ZOMATO.AI.REVIEW_ENRICHED;               -- SAMPLE_N rows after the first run
```

It is safe to run the DAG again. `COPY INTO` skips files that it already loaded, the incremental facts use `MERGE`, and the enrichment skips reviews that already have a row.

To see why a task failed, click the task in the UI and open **Logs**. After you fix the cause, clear the task. Airflow continues from that task.

### 4.2 Enrichment script (`enrich_reviews.py`)

The DAG runs this script with the `SAMPLE_N` value from `.env`. To enrich more reviews now, run it directly with a larger value:

```bash
docker compose exec -e SAMPLE_N=200 scheduler python /opt/airflow/ai/enrich_reviews.py
```

Local Ollama is slow. Start with 200, and increase the number later. Then refresh the AI mart:

```bash
docker compose exec scheduler /opt/airflow/dbt_venv/bin/dbt build --select tag:ai \
  --project-dir /opt/airflow/dbt/zomato --profiles-dir /opt/airflow/dbt/zomato
```

**Check:** `SELECT * FROM ZOMATO.MARTS.MART_REVIEW_INSIGHTS;` shows more rows.

### 4.3 dbt by hand (optional)

dbt runs in its own virtual environment in the container:

```bash
docker compose exec scheduler /opt/airflow/dbt_venv/bin/dbt debug \
  --project-dir /opt/airflow/dbt/zomato --profiles-dir /opt/airflow/dbt/zomato
docker compose exec scheduler /opt/airflow/dbt_venv/bin/dbt build --exclude tag:ai \
  --project-dir /opt/airflow/dbt/zomato --profiles-dir /opt/airflow/dbt/zomato
```

### 4.4 Streamlit apps (RAG and text-to-SQL)

Both apps use port 8501. **Run one app at a time.** Press `Ctrl+C` to stop an app before you start the other one.

**RAG — chat with the reviews:**
```bash
docker compose exec -w /opt/airflow/ai scheduler streamlit run rag_chat.py \
  --server.port 8501 --server.address 0.0.0.0 --server.headless true
```
Open <http://localhost:8501>.
- The first start is slow. The app downloads the embedding model and embeds 500 reviews. It saves them in `ai/review_embeddings.parquet`. Delete this file to build the embeddings again.
- Ask: "What are the most common complaints about delivery?" or "What do people say about packaging?"
- Open **Reviews used to build this answer**. The reviews must match the topic of your question.

**Text-to-SQL — chat with the warehouse:**
```bash
docker compose exec -w /opt/airflow/ai scheduler streamlit run text_to_sql.py \
  --server.port 8501 --server.address 0.0.0.0 --server.headless true
```
Open <http://localhost:8501> and ask:
- "Top 10 cities by GMV"
- "Which cuisine has the most orders?"
- "Average delivery time by city, worst first"
- "Cancel rate by payment method"
- "Give me the city with the most negative reviews" (this needs enriched reviews, see 4.2)
- "Drop the orders table" (the app must refuse with "not safe")

The app shows the SQL that the model wrote, then the result. Local models sometimes write weak SQL. If the answer looks wrong, rephrase the question.

---

## 5 · Stop and reset

| Goal | Command |
|---|---|
| Stop the containers, keep the Airflow data | `docker compose down` |
| Stop and delete the Airflow database (DAG history, users) | `docker compose down -v` |
| Start again | `docker compose up -d` |

To reload the raw tables from the start, recreate them with `snowflake/04_raw_tables.sql`, then trigger the DAG. A new table has no load history, so `COPY INTO` loads all files again.

## 6 · Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `no configuration file provided: not found` | You are not in the `airflow/` folder. Run `cd airflow`. |
| `reload_raw` fails with `Insufficient privileges` on the stage | `DBT_ROLE` has no `USAGE` on the stage or file format. Run `03_stage_and_formats.sql` again, or the two `GRANT USAGE` lines at its end. |
| `enrich_reviews` fails to connect to Ollama | Ollama does not run, or the model is missing. Repeat section 2.4. |
| `Object ... does not exist or not authorized` in text-to-SQL | A dbt model did not build. Run the DAG, or `dbt build`, and check that the table exists in `ZOMATO.MARTS`. |
| Port 8501 is in use | Another Streamlit app still runs. Stop it with `Ctrl+C`. |
| Port 8080 is in use | Another program uses the port. Stop it, or change the port in `docker-compose.yaml`. |
