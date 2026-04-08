# GCP Data ETL - Cloud Function Trigger

## Overview

This HTTP-triggered Cloud Function checks for a data file in a configured GCS bucket and, if found,
creates an ephemeral GCE VM to run a containerized import job. Before creating the VM, it checks
whether any watched VMs are already running to prevent duplicate or conflicting jobs.

All project-specific values (project ID, bucket, VM names, container image, etc.) are set in `config.py`.

---

## How It Works

### Trigger
- **Type**: HTTP (`@functions_framework.http`)
- **Invocation**: Call the function's URL directly, or chain it from a Cloud Scheduler job, Pub/Sub push, or any other HTTP-capable trigger.

### VM Conflict Check
Before doing anything, the function scans all GCE instances in the project and checks whether any
VM whose name contains a string from `vm_names_to_check` (config) is currently in a non-safe state.

**Safe states** (will not block execution): `TERMINATED`, `SUSPENDED`

**Blocking states** (function exits early): anything else — `RUNNING`, `PROVISIONING`, `STAGING`, `STOPPING`, etc.

If the GCP API call itself fails, the function exits with a `500` rather than risk launching a duplicate job.

### File Check
If no blocking VMs are found, the function lists all objects in the configured GCS bucket and looks
for one ending with the configured extension (default: `.sql.gz`). If no matching file is found,
the function exits with `200` and logs a message.

### VM Creation
If a matching file is found, the function creates an ephemeral GCE VM. The VM:
1. Pulls the configured container image from Artifact Registry
2. Runs the container
3. Should be configured to delete itself on completion (handled inside the container/startup script)

---

## Configuration

All values are set in [`config.py`](config.py). No code changes are needed for a new project — only update this file.

| Variable | Description |
|---|---|
| `project_id` | GCP project ID |
| `vm_names_to_check` | List of substrings — any running VM matching one will block execution |
| `bucket_name` | GCS bucket to scan for the data file |
| `zip_file_ends_with` | File extension to look for (default: `.sql.gz`) |
| `instance_name_str` | VM name prefix — a UTC timestamp is appended automatically |
| `zone` | GCP zone for the new VM (default: `us-central1-b`) |
| `container_image` | Full Artifact Registry path to the container image |
| `container_name` | Name assigned to the Docker container inside the VM |
| `service_account_email` | Service account the VM runs as |

---

## VM Specifications

| Property | Value |
|---|---|
| Machine type | `n2-standard-8` (8 vCPUs, 32 GB RAM) |
| OS | Container-Optimized OS (`cos-stable`) |
| Boot disk | 150 GB SSD (`pd-ssd`), auto-deleted with VM |
| Network | Default VPC with external NAT |
| Restart | Disabled (`automatic_restart=False`) |
| Preemptible | No |

---

## Function Reference

### `trigger_data_import(request)`
HTTP entry point. Orchestrates the VM conflict check, file check, and VM creation. Returns a
`(message, status_code)` tuple.

### `get_blocking_vm_status(project_id, vm_name_checks)`
Scans all GCE instances in the project. Returns `(None, None)` if safe to proceed,
`(vm_name, status)` if a blocking VM is found, or `(None, "ERROR")` if the API call fails.

### `create_vm(in_project_id, instance_name_str, zone, container_name, container_image_path, service_account_email)`
Creates the ephemeral GCE VM with a startup script that pulls and runs the configured container.

---

## Deployment

Deploy as a **Cloud Run function (2nd gen)** with an HTTP trigger.

The Cloud Function's service account needs:
- `compute.instances.list` / `compute.instances.insert` (to check and create VMs)
- `storage.objects.list` (to scan the GCS bucket)

The **VM's** service account (set in `config.py`) needs whatever the container itself requires
(e.g. Storage read, Secret Manager access, Logging write).

---
