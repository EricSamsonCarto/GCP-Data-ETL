
# GCP project ID
project_id = 'your-project-id'

# GCS bucket that holds the data file to import
bucket_name = 'your-data-bucket'

# File extension used to identify the data file in the bucket
zip_file_ends_with = '.sql.gz'

# Secret Manager secret IDs for database credentials.
# The VM's service account must have Secret Manager Secret Accessor on each of these.
db_user_secret_id = 'your-db-user-secret'
db_password_secret_id = 'your-db-password-secret'
db_host_secret_id = 'your-db-host-secret'

# Non-sensitive database connection values
db_port = '5432'
db_name = 'your-database-name'

# Directory inside the container where SQL index files are located.
# This should match the WORKDIR in the Dockerfile (default: /app).
index_dir = '/app'

# Timeout (in minutes) applied to the index creation SQL file.
# Increase this for large datasets with many or expensive indexes.
index_timeout_minutes = 120

# Whether to delete the VM after the job completes.
# Set the AUTO_SHUTDOWN environment variable to 'false' to override at runtime
# without rebuilding the container (useful for debugging).
auto_shutdown = True
