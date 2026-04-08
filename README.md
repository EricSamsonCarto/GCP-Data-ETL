# GCP Data ETL

## Overview

This repo automates a recurring data ETL pipeline entirely within GCP. When a data file appears in a Cloud Storage bucket, the system streams it into a PostgreSQL database, builds indexes, cleans up, and destroys itself — all without manual intervention.

The pipeline uses four GCP services:

- **Cloud Scheduler** — triggers the Cloud Function on a schedule
- **Cloud Run Function** — checks for a data file and spins up a VM if one is found
- **Compute Engine** — ephemeral VM that runs the Docker container
- **Artifact Registry** — hosts the Docker image the VM pulls at startup

All project-specific values are set in `config.py` files — one for the Cloud Function and one for the VM container. No hardcoded values exist in the source code.

---

## Repository Structure

```
data_etl_vm/
├── core/
│   ├── __init__.py
│   └── sql_import_funcs.py
├── sql/
│   └── create_indexes.sql
├── config.py
├── dockerfile
├── main.py
└── requirements.txt
cloud_function/
├── cloud_function_readme.md
├── config.py
├── gcp_cloud_function.py
└── requirements.txt
docker_notes.txt
.gitignore
README.md
```

---

## Guide

### Phase 1: Service Account Setup

Create three service accounts — one for each component that needs its own identity and permissions.

**Cloud Scheduler SA** (`your-scheduler-sa`)
- Cloud Run Invoker

**Cloud Function SA** (`your-cloud-function-sa`)
- Compute Instance Admin (v1)
- Service Account User
- Storage Object Viewer

**VM SA** (`your-vm-sa`)
- Storage Object Viewer
- Storage Object Admin *(if the VM deletes the source file after import)*
- Secret Manager Secret Accessor
- Logs Writer
- Compute Instance Admin (v1) *(for self-deletion)*

For each service account:
1. Go to **IAM & Admin → Service Accounts**
2. Click **Create Service Account**, give it a name and description
3. Assign the roles listed above

---

### Phase 2: Secret Manager Setup

The VM reads database credentials from Secret Manager at runtime. Add the following secrets:

- Database username
- Database password
- Database host

The secret IDs you choose here must match the `db_user_secret_id`, `db_password_secret_id`, and `db_host_secret_id` values in `data_etl_vm/config.py`.

---

### Phase 3: Configure `config.py` Files

There are two `config.py` files — one per component. Fill in the placeholders before deploying.

**`cloud_function/config.py`** — controls VM creation:

| Variable | Description |
|---|---|
| `project_id` | GCP project ID |
| `vm_names_to_check` | List of VM name substrings that should block a new run |
| `bucket_name` | GCS bucket to check for the data file |
| `zip_file_ends_with` | File extension to look for (default: `.sql.gz`) |
| `instance_name_str` | VM name prefix (timestamp appended automatically) |
| `zone` | GCP zone for the VM |
| `container_image` | Full Artifact Registry path to the container image |
| `container_name` | Docker container name inside the VM |
| `service_account_email` | VM service account email |

**`data_etl_vm/config.py`** — controls the import job:

| Variable | Description |
|---|---|
| `project_id` | GCP project ID |
| `bucket_name` | GCS bucket containing the data file |
| `zip_file_ends_with` | File extension to look for (default: `.sql.gz`) |
| `db_user_secret_id` | Secret Manager ID for the DB username |
| `db_password_secret_id` | Secret Manager ID for the DB password |
| `db_host_secret_id` | Secret Manager ID for the DB host |
| `db_port` | Database port (default: `5432`) |
| `db_name` | Database name |
| `index_dir` | Directory inside the container with `create_indexes.sql` (default: `/app`) |
| `index_timeout_minutes` | Timeout for the index SQL file (default: `120`) |
| `auto_shutdown` | Whether to delete the VM on completion (default: `True`) |

---

### Phase 4: Customize the SQL File

Edit `data_etl_vm/sql/create_indexes.sql` to add any post-import SQL your project needs — indexes, table renames, views, cleanup, etc. This file runs automatically after the data import completes.

The file ships with commented-out examples for common index types (B-tree, GIN trigram, GiST spatial) and table finalization patterns.

---

### Phase 5: Build and Push the Docker Image

From the `data_etl_vm/` directory, run the following commands with Docker open on your desktop.

**Build the image:**
```bash
docker build -t your-image-name .
```

**Tag it for Artifact Registry:**
```bash
docker tag your-image-name REGION-docker.pkg.dev/YOUR_PROJECT/YOUR_REPO/YOUR_IMAGE
```

**Authenticate Docker with GCP:**
```bash
gcloud auth print-access-token | docker login -u oauth2accesstoken --password-stdin https://REGION-docker.pkg.dev
```

**Push to Artifact Registry:**
```bash
docker push REGION-docker.pkg.dev/YOUR_PROJECT/YOUR_REPO/YOUR_IMAGE
```

Before pushing, create an Artifact Registry repository to push to:
1. Go to **Artifact Registry → Create Repository**
2. Set format to **Docker**, choose your region, give it a name
3. Use that repository path in the tag and push commands above

The full image path you end up with is what goes into `container_image` in `cloud_function/config.py`.

> **Note:** To skip VM self-deletion during testing (e.g. to inspect logs), set the `AUTO_SHUTDOWN` environment variable to `false` in your Docker run command or VM startup script — no container rebuild needed.

---

### Phase 6: Deploy the Cloud Function

The Cloud Function code lives in `cloud_function/gcp_cloud_function.py` with its own `config.py`.

Deploy as a Cloud Run Function (2nd gen) with an HTTP trigger:

```bash
gcloud functions deploy your-function-name \
  --gen2 \
  --runtime=python311 \
  --region=us-central1 \
  --source=./cloud_function \
  --entry-point=trigger_data_import \
  --trigger-http \
  --service-account=your-cloud-function-sa@YOUR_PROJECT.iam.gserviceaccount.com
```

Alternatively, via the GCP console:
1. Go to **Cloud Run → Write a Function**
2. Choose Python 3.11, HTTP trigger, require authentication, internal ingress
3. Assign the Cloud Function service account
4. In the **Source** tab, paste the contents of `gcp_cloud_function.py` into `main.py` and `config.py` into a new `config.py` file
5. Add the contents of `cloud_function/requirements.txt`

The function checks for running VMs that match any name in `vm_names_to_check` before proceeding. This prevents duplicate jobs from overlapping if the scheduler fires while a previous import is still running.

---

### Phase 7: Set Up Cloud Scheduler

Create a Cloud Scheduler job to trigger the Cloud Function on your desired schedule:

1. Go to **Cloud Scheduler → Create Job**
2. Fill in:
   - **Name**, **Region**, **Description**
   - **Frequency**: e.g. `5 22 * * *` (10:05 PM daily in cron format)
   - **Timezone**: your local timezone
3. Under **Execution**:
   - **Target type**: HTTP
   - **URL**: the Cloud Run Function URL from Phase 6
   - **HTTP method**: GET
   - **Auth header**: OIDC token
   - **Service account**: your Scheduler SA

Click **Run Now** to verify the trigger works end-to-end and check the Cloud Function logs.

---

### Phase 8: Cloud Logging Alerts

Set up log-based alerts so you're notified when the import succeeds, fails, or the VM deletes itself.

Go to **Logging → Logs Explorer** and create an alert for each query below.

**Import completed successfully:**
```
resource.type="gce_instance"
jsonPayload.message=~"data import completed successfully"
```

**Import failed:**
```
resource.type="gce_instance"
jsonPayload.message=~"data import failed"
severity="ERROR"
```

**VM self-deletion initiated:**
```
resource.type="gce_instance"
jsonPayload.message=~"deleting vm"
```

In the query results bar, click **Actions → Create Log Alert** to configure notification channels (email, PagerDuty, etc.).

---

## Pipeline Flow

Each time Cloud Scheduler fires:

1. Cloud Scheduler triggers the Cloud Function via HTTP
2. Cloud Function checks for any running VMs matching `vm_names_to_check`
   - If a blocking VM is found → exits early (no duplicate job)
3. Cloud Function checks the GCS bucket for a file ending with `zip_file_ends_with`
   - If no file → logs "No file found", exits
4. File found → Cloud Function creates an ephemeral VM
5. VM starts, pulls the container image from Artifact Registry
6. Container runs `main.py`, which:
   - Reads DB credentials from Secret Manager
   - Streams the data file from GCS into PostgreSQL via `gsutil | gunzip | psql`
   - Executes `create_indexes.sql` (indexes, renames, views, etc.)
   - Deletes the source file from GCS
   - Logs completion
   - Deletes the VM
7. Cloud Logging alerts fire on success, failure, or VM deletion
