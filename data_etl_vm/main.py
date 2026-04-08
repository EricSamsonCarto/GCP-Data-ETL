import os
import sys
import logging

from core.sql_import_funcs import *
from config import bucket_name, index_dir, auto_shutdown


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point for the ETL import job.

    Orchestrates the full pipeline:
    1. Locate the data file in GCS
    2. Stream-import it into the database via psql
    3. Build indexes on the imported data
    4. Delete the source file from GCS
    5. Shut down the VM (unless disabled via AUTO_SHUTDOWN=false)
    """
    try:
        logger.info("=" * 50)
        logger.info("data import starting")
        logger.info(f"bucket: {bucket_name}")
        logger.info(f"index dir: {index_dir}")
        logger.info("=" * 50)

        result = find_gz_file(bucket_name)
        if not result:
            logger.error("no data file found in bucket, exiting")
            sys.exit(1)

        blob_name, _ = result

        db_config = get_db_config()
        gs_gz_path = get_gs_path(bucket_name, blob_name)
        run_psql_import(gs_gz_path, db_config)
        create_indexes(db_config, index_dir)
        delete_file(bucket_name, blob_name)

        logger.info("=" * 50)
        logger.info("data import completed successfully")
        logger.info("=" * 50)

    except Exception as e:
        logger.error("=" * 50)
        logger.error("data import failed")
        logger.error(f"error: {str(e)}")
        logger.error("=" * 50)
        raise

    finally:
        # AUTO_SHUTDOWN env var overrides the config value — set to 'false' to keep
        # the VM alive for debugging without rebuilding the container image.
        should_shutdown = os.environ.get('AUTO_SHUTDOWN', str(auto_shutdown)).lower() == 'true'
        if should_shutdown:
            shutdown_vm()


if __name__ == "__main__":
    main()
