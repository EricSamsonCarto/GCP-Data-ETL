import os
import sys
import subprocess
import logging
import traceback
import requests

from pathlib import Path
from datetime import datetime
from typing import Optional, Dict
from google.cloud import storage
from google.cloud import secretmanager
from google.cloud import compute_v1

from config import (
    project_id,
    db_user_secret_id, db_password_secret_id, db_host_secret_id,
    db_port, db_name,
    zip_file_ends_with,
    index_timeout_minutes,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def access_secret(secret_id: str, project_id: str, client) -> str:
    """Access a single secret from GCP Secret Manager.

    Args:
        secret_id: The secret name in Secret Manager.
        project_id: GCP project ID.
        client: A SecretManagerServiceClient instance.

    Returns:
        The secret value as a decoded string.
    """
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def get_list_secrets(in_ids_list: list, in_proj_id: str, in_goog_client) -> Dict[str, str]:
    """Retrieve multiple secrets from Secret Manager in one call.

    Args:
        in_ids_list: List of secret IDs to retrieve.
        in_proj_id: GCP project ID.
        in_goog_client: A SecretManagerServiceClient instance.

    Returns:
        A dict mapping each secret ID to its value.
    """
    secrets_returned = []
    for secret_id in in_ids_list:
        current_secret = access_secret(secret_id, in_proj_id, in_goog_client)
        secrets_returned.append(current_secret)

    return {key: value for key, value in zip(in_ids_list, secrets_returned)}


def get_db_config() -> Dict[str, str]:
    """Retrieve database credentials from Secret Manager and assemble a connection config.

    Reads the secret IDs and non-sensitive connection values from config.py.
    The VM's service account must have Secret Manager Secret Accessor on each secret.

    Returns:
        A dict with keys: host, port, database, user, password.
    """
    secret_client = secretmanager.SecretManagerServiceClient()
    secret_ids = [db_user_secret_id, db_password_secret_id, db_host_secret_id]
    secrets = get_list_secrets(secret_ids, project_id, secret_client)

    return {
        'host': secrets[db_host_secret_id],
        'port': db_port,
        'database': db_name,
        'user': secrets[db_user_secret_id],
        'password': secrets[db_password_secret_id],
    }


def find_gz_file(bucket_name: str) -> Optional[tuple[str, str]]:
    """Find the first matching data file in a GCS bucket.

    Searches for a blob whose name ends with the configured zip_file_ends_with
    extension (set in config.py).

    Args:
        bucket_name: GCS bucket name to search.

    Returns:
        A tuple of (blob_name, blob_name) if a matching file is found, or None.
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    for blob in bucket.list_blobs():
        if blob.name.endswith(zip_file_ends_with):
            logger.info(f"found data file: {blob.name}")
            return blob.name, blob.name

    logger.warning(f"no file ending with '{zip_file_ends_with}' found in bucket '{bucket_name}'")
    return None


def get_gs_path(bucket_name: str, blob_name: str) -> str:
    """Build the full gs:// path for a GCS object.

    Args:
        bucket_name: GCS bucket name.
        blob_name: Object path within the bucket.

    Returns:
        The full GCS URI as a string (e.g. gs://bucket/path/to/file).
    """
    gs_path = f"gs://{bucket_name}/{blob_name}"
    logger.info(f"data file location: {gs_path}")
    return gs_path


def run_psql_import(gs_zip_path: str, db_config: Dict[str, str]) -> None:
    """Stream a compressed SQL file from GCS directly into the database.

    Uses gsutil cat piped through gunzip and into psql, avoiding the need to
    fully download the file before importing.

    Args:
        gs_zip_path: GCS URI to the compressed SQL file (gs://bucket/path).
        db_config: Database connection dict with keys: host, port, database, user, password.

    Raises:
        subprocess.CalledProcessError: If psql exits with a non-zero status.
    """
    logger.info("starting streaming psql import...")
    start_time = datetime.now()

    os.environ['PGPASSWORD'] = db_config['password']

    statement = (
        f"gsutil cat {gs_zip_path} | gunzip | "
        f"psql -h {db_config['host']} "
        f"-p {db_config['port']} "
        f"-U {db_config['user']} "
        f"-d {db_config['database']} "
        f"-v ON_ERROR_STOP=1"
    )

    try:
        result = subprocess.run(
            statement,
            shell=True,
            capture_output=True,
            text=True,
            check=True,
        )

        duration = (datetime.now() - start_time).total_seconds() / 60
        logger.info(f"psql import completed successfully in {duration:.2f} minutes")

        if result.stdout:
            logger.info(f"psql output: {result.stdout[:500]}")

    except subprocess.CalledProcessError as e:
        logger.error(f"psql import failed: {e.stderr}")
        raise


def run_sql_file(db_config: Dict[str, str], sql_file: str, timeout_minutes: int = 30) -> None:
    """Execute a SQL file against the database via psql.

    Args:
        db_config: Database connection dict with keys: host, port, database, user, password.
        sql_file: Absolute or relative path to the .sql file to execute.
        timeout_minutes: Per-statement timeout passed to PostgreSQL. Defaults to 30 minutes.

    Raises:
        subprocess.CalledProcessError: If psql exits with a non-zero status.
    """
    if not os.path.exists(sql_file):
        logger.warning(f"sql file not found, skipping: {sql_file}")
        return

    logger.info(f"executing sql file: {sql_file}")
    start_time = datetime.now()

    os.environ['PGPASSWORD'] = db_config['password']
    timeout_ms = timeout_minutes * 60 * 1000

    statement = (
        f"psql -h {db_config['host']} "
        f"-p {db_config['port']} "
        f"-U {db_config['user']} "
        f"-d {db_config['database']} "
        f"-c 'SET statement_timeout = {timeout_ms};' "
        f"-f {sql_file} "
        f"-v ON_ERROR_STOP=1"
    )

    try:
        subprocess.run(statement, shell=True, capture_output=True, text=True, check=True)
        duration = (datetime.now() - start_time).total_seconds() / 60
        logger.info(f"sql file executed successfully in {duration:.2f} minutes")
    except subprocess.CalledProcessError as e:
        logger.error(f"sql execution failed: {e.stderr}")
        raise


def create_indexes(db_config: Dict[str, str], index_dir: str) -> None:
    """Execute the post-import SQL file (indexes, renames, views, etc.).

    Runs create_indexes.sql from index_dir against the database. The statement
    timeout is controlled by index_timeout_minutes in config.py.

    Args:
        db_config: Database connection dict with keys: host, port, database, user, password.
        index_dir: Directory containing create_indexes.sql (typically /app inside the container).

    Raises:
        subprocess.CalledProcessError: If psql exits with a non-zero status.
    """
    sql_file = f'{index_dir}/create_indexes.sql'

    logger.info("=" * 50)
    logger.info(f"running post-import SQL: {sql_file}")
    logger.info("=" * 50)

    start = datetime.now()
    try:
        run_sql_file(db_config, sql_file, index_timeout_minutes)
    except Exception as e:
        logger.error(f"post-import SQL failed: {e}")
        raise

    duration = (datetime.now() - start).total_seconds() / 60
    logger.info("=" * 50)
    logger.info(f"post-import SQL completed in {duration:.2f} minutes")
    logger.info("=" * 50)


def delete_file(bucket_name: str, blob_name: str) -> None:
    """Delete a file from a GCS bucket.

    Args:
        bucket_name: GCS bucket name.
        blob_name: Path to the object within the bucket.
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    blob.delete()
    logger.info(f"deleted file from bucket: {blob_name}")


def shutdown_vm() -> None:
    """Delete the current GCE VM instance by querying the instance metadata server.

    Reads the instance name, zone, and project ID from the GCE metadata API,
    then issues a delete request via the Compute API. Logs an error and returns
    gracefully if any step fails so that the main process can still exit cleanly.
    """
    logger.info("deleting vm...")
    try:
        metadata_base_url = "http://metadata.google.internal/computeMetadata/v1"
        headers = {"Metadata-Flavor": "Google"}

        instance_response = requests.get(
            f"{metadata_base_url}/instance/name",
            headers=headers,
            timeout=5,
        )
        if instance_response.status_code != 200:
            logger.error(f"failed to get instance name: status {instance_response.status_code}")
            return
        instance_name = instance_response.text.strip()
        logger.info(f"retrieved instance name: {instance_name}")

        zone_response = requests.get(
            f"{metadata_base_url}/instance/zone",
            headers=headers,
            timeout=5,
        )
        if zone_response.status_code != 200:
            logger.error(f"failed to get zone: status {zone_response.status_code}")
            return
        zone = zone_response.text.strip().split('/')[-1]
        logger.info(f"retrieved zone: {zone}")

        project_response = requests.get(
            f"{metadata_base_url}/project/project-id",
            headers=headers,
            timeout=5,
        )
        if project_response.status_code != 200:
            logger.error(f"failed to get project id: status {project_response.status_code}")
            return
        project = project_response.text.strip()
        logger.info(f"retrieved project: {project}")

        logger.info(f"initiating self-deletion: project={project}, zone={zone}, instance={instance_name}")

        instance_client = compute_v1.InstancesClient()
        delete_request = compute_v1.DeleteInstanceRequest(
            project=project,
            zone=zone,
            instance=instance_name,
        )
        operation = instance_client.delete(request=delete_request)
        logger.info(f"vm deletion initiated: operation={operation.name if hasattr(operation, 'name') else 'N/A'}")

    except Exception as e:
        logger.error(f"failed to delete vm: {e}")
        logger.error(traceback.format_exc())
