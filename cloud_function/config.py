
# Your GCP project ID
project_id = 'your-project-id'

# One or more substrings to match against VM names.
# If any running VM's name contains one of these strings, the function will exit early
# to avoid running conflicting jobs simultaneously.
vm_names_to_check = ['large-vm']

# GCS bucket name that holds the data file to import
bucket_name = 'data-bucket'

# File extension used to identify the data file in the bucket
# Default: .sql.gz
zip_file_ends_with = '.sql.gz'

# Prefix for the new VM name. A timestamp is appended automatically (e.g. data-etl-20240318-120000)
instance_name_str = 'data-etl'

# GCP zone to create the VM in
# Default: us-central1-b
zone = 'us-central1-b'

# Full Artifact Registry path to the container image
# Example: us-central1-docker.pkg.dev/your-project/your-repo/your-image:tag
container_image = 'us-central1-docker.pkg.dev/your-project/your-repo/your-image:latest'

# Name to assign to the running container inside the VM
container_name = 'data-etl'

# Service account email the VM will run as.
# Must have permissions for: Artifact Registry (read), Cloud Storage (read/write), and any other resources your container needs.
service_account_email = 'your-service-account@your-project-id.iam.gserviceaccount.com'
