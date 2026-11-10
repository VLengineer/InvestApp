#!/bin/bash
set -euo pipefail

echo "=== Backup started at $(date '+%Y-%m-%d %H:%M:%S') ==="

# ── 1. PostgreSQL dump ───────────────────────────────────────────────
echo "[1/3] Dumping PostgreSQL database..."

PGDUMP_FILE="/tmp/pg_dump_$(date +%Y%m%d_%H%M%S).sql.gz"

PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
    -h postgres \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}" \
    --clean --if-exists \
    --no-owner --no-privileges \
    | gzip > "${PGDUMP_FILE}"

echo "  → PostgreSQL dump: $(du -h "${PGDUMP_FILE}" | cut -f1)"

# ── 2. n8n data backup ───────────────────────────────────────────────
echo "[2/3] Backing up n8n data..."

N8N_BACKUP_DIR="/tmp/n8n_backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "${N8N_BACKUP_DIR}"

# Копируем содержимое n8n volume (смонтирован в /n8n_data)
if [ -d "/n8n_data" ] && [ "$(ls -A /n8n_data 2>/dev/null)" ]; then
    cp -a /n8n_data/* "${N8N_BACKUP_DIR}/" 2>/dev/null || true
    echo "  → n8n data: $(du -sh "${N8N_BACKUP_DIR}" | cut -f1)"
else
    echo "  → n8n data directory is empty or missing, skipping"
fi

# ── 3. Restic backup + prune ─────────────────────────────────────────
echo "[3/3] Running restic backup..."

# Бэкап PostgreSQL dump
restic backup "${PGDUMP_FILE}" \
    --tag postgres \
    --tag automated \
    --host "${RESTIC_HOST:-n8n-server}"

# Бэкап n8n data
if [ -d "${N8N_BACKUP_DIR}" ] && [ "$(ls -A "${N8N_BACKUP_DIR}" 2>/dev/null)" ]; then
    restic backup "${N8N_BACKUP_DIR}" \
        --tag n8n \
        --tag automated \
        --host "${RESTIC_HOST:-n8n-server}"
fi

# ── 4. Retention policy (forget + prune) ─────────────────────────────
echo "Applying retention policy..."

restic forget \
    --keep-daily "${RESTIC_KEEP_DAILY:-7}" \
    --keep-weekly "${RESTIC_KEEP_WEEKLY:-4}" \
    --keep-monthly "${RESTIC_KEEP_MONTHLY:-6}" \
    --prune

# ── 5. Cleanup temp files ────────────────────────────────────────────
rm -rf "${PGDUMP_FILE}" "${N8N_BACKUP_DIR}"

echo "=== Backup completed at $(date '+%Y-%m-%d %H:%M:%S') ==="
