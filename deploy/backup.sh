#!/usr/bin/env sh
# Sauvegarde quotidienne de data/ (comptes, clés chiffrées, séances, mémoire).
# À lancer depuis le dossier du dépôt sur le serveur, par cron :
#   15 3 * * * cd /home/coach/Ai-Coach-V2 && ./deploy/backup.sh >> backups/backup.log 2>&1
# Garde KEEP_DAYS archives (7 par défaut). Copie ensuite backups/ hors du
# serveur (Storage Box, rclone…) : une sauvegarde sur le même disque ne
# protège pas d'une panne du serveur.
set -eu

KEEP_DAYS="${KEEP_DAYS:-7}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
stamp="$(date +%Y-%m-%d_%H%M)"

mkdir -p "$BACKUP_DIR"
tar -czf "$BACKUP_DIR/data-$stamp.tar.gz" data
find "$BACKUP_DIR" -name 'data-*.tar.gz' -mtime +"$KEEP_DAYS" -delete
echo "$(date -Iseconds) sauvegarde $BACKUP_DIR/data-$stamp.tar.gz"
