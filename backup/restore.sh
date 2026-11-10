#!/bin/bash
set -euo pipefail

# ── Функции помощи ───────────────────────────────────────────────────
usage() {
    cat <<EOF
Использование: $0 [OPTIONS] <SNAPSHOT_ID>

Восстановление из restic снапшота.

ОПЦИИ:
    --list              Показать список доступных снапшотов
    --postgres-only     Восстановить только PostgreSQL
    --n8n-only          Восстановить только n8n данные
    --force             Не спрашивать подтверждение
    -h, --help          Показать эту помощь

ПРИМЕРЫ:
    $0 --list                          # Показать снапшоты
    $0 abc123                          # Восстановить всё из снапшота abc123
    $0 --postgres-only abc123          # Восстановить только PostgreSQL
    $0 --n8n-only abc123               # Восстановить только n8n
    $0 --force abc123                  # Восстановить без подтверждения

ВАЖНО:
    - Перед восстановлением PostgreSQL остановите все сервисы, кроме postgres
    - n8n данные восстанавливаются в /n8n_data (read-write volume)
    - После восстановления перезапустите сервисы
EOF
    exit 0
}

# ── Парсинг аргументов ───────────────────────────────────────────────
RESTORE_POSTGRES=true
RESTORE_N8N=true
FORCE=false
SNAPSHOT_ID=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --list)
            echo "Доступные снапшоты:"
            restic snapshots
            exit 0
            ;;
        --postgres-only)
            RESTORE_N8N=false
            shift
            ;;
        --n8n-only)
            RESTORE_POSTGRES=false
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        -*)
            echo "Неизвестная опция: $1"
            usage
            ;;
        *)
            SNAPSHOT_ID="$1"
            shift
            ;;
    esac
done

if [ -z "${SNAPSHOT_ID}" ]; then
    echo "Ошибка: не указан ID снапшота"
    usage
fi

# ── Проверка снапшота ────────────────────────────────────────────────
echo "Проверяю снапшот ${SNAPSHOT_ID}..."
if ! restic snapshots "${SNAPSHOT_ID}" >/dev/null 2>&1; then
    echo "Ошибка: снапшот ${SNAPSHOT_ID} не найден"
    echo "Используйте --list для просмотра доступных снапшотов"
    exit 1
fi

# ── Подтверждение ────────────────────────────────────────────────────
if [ "${FORCE}" != "true" ]; then
    echo ""
    echo "ВНИМАНИЕ: Вы собираетесь восстановить данные из снапшота ${SNAPSHOT_ID}"
    [ "${RESTORE_POSTGRES}" = "true" ] && echo "  - PostgreSQL будет восстановлен"
    [ "${RESTORE_N8N}" = "true" ] && echo "  - n8n данные будут восстановлены"
    echo ""
    echo "Это действие перезапишет текущие данные!"
    read -p "Продолжить? (yes/no): " -r
    if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        echo "Отменено"
        exit 0
    fi
fi

# ── Восстановление PostgreSQL ────────────────────────────────────────
if [ "${RESTORE_POSTGRES}" = "true" ]; then
    echo ""
    echo "=== Восстановление PostgreSQL ==="
    
    # Создаём временную директорию
    RESTORE_DIR="/tmp/restore_$(date +%s)"
    mkdir -p "${RESTORE_DIR}"
    
    # Восстанавливаем снапшот с тегом postgres
    echo "Извлекаю файлы из снапшота..."
    restic restore "${SNAPSHOT_ID}" --target "${RESTORE_DIR}" --include "*pg_dump*.sql.gz" || {
        echo "Ошибка: не удалось восстановить файлы из снапшота"
        rm -rf "${RESTORE_DIR}"
        exit 1
    }
    
    # Находим файл дампа
    DUMP_FILE=$(find "${RESTORE_DIR}" -name "pg_dump_*.sql.gz" -type f | head -1)
    
    if [ -z "${DUMP_FILE}" ]; then
        echo "Ошибка: файл дампа PostgreSQL не найден в снапшоте"
        rm -rf "${RESTORE_DIR}"
        exit 1
    fi
    
    echo "Найден дамп: ${DUMP_FILE}"
    echo "Размер: $(du -h "${DUMP_FILE}" | cut -f1)"
    
    # Восстанавливаем в PostgreSQL
    echo "Восстанавливаю базу данных..."
    gunzip -c "${DUMP_FILE}" | PGPASSWORD="${POSTGRES_PASSWORD}" psql \
        -h postgres \
        -U "${POSTGRES_USER}" \
        -d "${POSTGRES_DB}" \
        --single-transaction \
        --set ON_ERROR_STOP=on
    
    echo "✓ PostgreSQL восстановлен"
    
    # Очистка
    rm -rf "${RESTORE_DIR}"
fi

# ── Восстановление n8n ───────────────────────────────────────────────
if [ "${RESTORE_N8N}" = "true" ]; then
    echo ""
    echo "=== Восстановление n8n данных ==="
    
    # Создаём временную директорию
    RESTORE_DIR="/tmp/restore_n8n_$(date +%s)"
    mkdir -p "${RESTORE_DIR}"
    
    # Восстанавливаем снапшот с тегом n8n
    echo "Извлекаю n8n данные из снапшота..."
    restic restore "${SNAPSHOT_ID}" --target "${RESTORE_DIR}" --include "*n8n_backup_*" || {
        echo "Ошибка: не удалось восстановить n8n данные из снапшота"
        rm -rf "${RESTORE_DIR}"
        exit 1
    }
    
    # Находим директорию с данными
    N8N_RESTORE_DIR=$(find "${RESTORE_DIR}" -type d -name "n8n_backup_*" | head -1)
    
    if [ -z "${N8N_RESTORE_DIR}" ] || [ ! "$(ls -A "${N8N_RESTORE_DIR}" 2>/dev/null)" ]; then
        echo "Предупреждение: n8n данные не найдены в снапшоте (возможно, были пусты на момент бэкапа)"
        rm -rf "${RESTORE_DIR}"
    else
        echo "Найдены n8n данные: ${N8N_RESTORE_DIR}"
        echo "Размер: $(du -sh "${N8N_RESTORE_DIR}" | cut -f1)"
        
        # Очищаем текущий n8n_data
        echo "Очищаю текущие n8n данные..."
        rm -rf /n8n_data/*
        
        # Копируем восстановленные данные
        echo "Копирую восстановленные данные..."
        cp -a "${N8N_RESTORE_DIR}"/* /n8n_data/
        
        echo "✓ n8n данные восстановлены"
        
        # Очистка
        rm -rf "${RESTORE_DIR}"
    fi
fi

echo ""
echo "=== Восстановление завершено ==="
echo ""
echo "Следующие шаги:"
echo "  1. Перезапустите сервисы: docker compose restart"
echo "  2. Проверьте работоспособность"
echo "  3. Проверьте логи: docker compose logs -f"
