# PAPRI Project - Operations Guide

This document provides essential operational procedures for maintaining the PAPRI application in a production environment.

## 1. Backup and Recovery Strategy

A robust backup and recovery strategy is critical to prevent data loss. This covers both the primary relational database (MySQL) and the vector database (Qdrant).

### 1.1. MySQL Database

* **Recovery Point Objective (RPO):** 24 hours (we can tolerate losing up to 24 hours of data).
* **Recovery Time Objective (RTO):** 2 hours (the service should be restored within 2 hours of a catastrophic failure).
* **Method:** Daily automated backups using `mysqldump`.
* **Storage:** Backups should be stored in a secure, versioned, and geographically redundant location (e.g., AWS S3, Google Cloud Storage) with lifecycle policies to manage old backups (e.g., keep daily for 7 days, weekly for 1 month, monthly for 1 year).

#### **Example Backup Command:**

This command should be run by a cron job or a similar scheduler on a secure server that has access to the database.

```bash
#!/bin/bash
# Ensure DB credentials are set as environment variables
# DB_USER, DB_PASSWORD, DB_HOST, DB_NAME

BACKUP_DIR="/path/to/local/backups"
TIMESTAMP=<span class="math-inline">\(date \+%Y%m%d%H%M%S\)
BACKUP\_FILE\="</span>{BACKUP_DIR}/papri_db_backup_${TIMESTAMP}.sql.gz"

echo "Starting MySQL backup for ${DB_NAME}..."

# Create a compressed dump of the database, including routines and triggers.
# --single-transaction is crucial for InnoDB tables to get a consistent snapshot without locking tables.
mysqldump -u "$DB_USER" -p"$DB_PASSWORD" -h "$DB_HOST" \
  --single-transaction \
  --routines \
  --triggers \
  "$DB_NAME" | gzip > "$BACKUP_FILE"

if [ $? -eq 0 ]; then
  echo "Backup successful: ${BACKUP_FILE}"
  # Optional: Upload to cloud storage (e.g., AWS S3)
  # aws s3 cp "$BACKUP_FILE" "s3://your-papri-backups-bucket/mysql/"
else
  echo "Backup FAILED for ${DB_NAME}" >&2
  exit 1
fi
