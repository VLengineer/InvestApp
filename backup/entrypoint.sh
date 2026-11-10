#!/bin/bash
set -euo pipefail

# ── 1. Инициализация restic репозитория (если ещё не создан) ─────────
echo "Initializing restic repository..."
restic init 2>/dev/null || echo "Repository already initialized"

# ── 2. Проверка репозитория ──────────────────────────────────────────
echo "Verifying repository..."
restic snapshots >/dev/null

# ── 3. Настройка cron ────────────────────────────────────────────────
CRON_SCHEDULE="${RESTIC_CRON_SCHEDULE:-0 2 * * *}"

echo "Setting up cron schedule: ${CRON_SCHEDULE}"

# Создаём crontab
echo "${CRON_SCHEDULE} /backup.sh >> /var/log/backup.log 2>&1" > /etc/crontabs/root

# ── 4. Первый запуск (опционально) ───────────────────────────────────
if [ "${RESTIC_RUN_ON_STARTUP:-false}" = "true" ]; then
    echo "Running initial backup..."
    /backup.sh
fi

# ── 5. Запуск cron в foreground ──────────────────────────────────────
echo "Starting cron daemon..."
echo "Backup schedule: ${CRON_SCHEDULE}"
echo "Logs: tail -f /var/log/backup.log"

# crond в foreground режиме
exec crond -f -l 8
