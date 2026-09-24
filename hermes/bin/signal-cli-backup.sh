#!/bin/sh
# Nightly encrypted backup of Mickey's signal-cli account (identity keys + account DB).
# Consistent: SQLite online .backup (DB is WAL). Encrypted with age to the public key in
# /etc/signal-cli-backup.recipient; the private key lives only in k8s secret hermes/signal-cli-backup-key.
# Output: /var/backups/signal-cli (14 days) — copied off node1 to a Longhorn PVC by CronJob hermes/signal-cli-backup-offnode.
set -eu
SRC=/home/ubuntu/.local/share/signal-cli/data
OUT=/var/backups/signal-cli
RCPT=$(cat /etc/signal-cli-backup.recipient)
TS=$(date -u +%Y-%m-%dT%H%M%SZ)
umask 077
mkdir -p "$OUT"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/data"
for f in "$SRC"/*; do [ -f "$f" ] && cp -p "$f" "$T/data/"; done          # accounts.json + account JSON (keys)
for d in "$SRC"/*.d; do
  n=$(basename "$d"); mkdir -p "$T/data/$n"
  sqlite3 "$d/account.db" ".backup '$T/data/$n/account.db'"
  [ "$(sqlite3 "$T/data/$n/account.db" 'pragma integrity_check;')" = ok ]
  for f in "$d"/*; do case "$f" in *account.db|*account.db-wal|*account.db-shm) ;; *) [ -f "$f" ] && cp -p "$f" "$T/data/$n/";; esac; done
done
tar -C "$T" -czf - data | age -r "$RCPT" > "$OUT/signal-cli-$TS.tar.gz.age.partial"
mv "$OUT/signal-cli-$TS.tar.gz.age.partial" "$OUT/signal-cli-$TS.tar.gz.age"
find "$OUT" -name 'signal-cli-*.tar.gz.age' -mtime +14 -delete
echo "ok: $OUT/signal-cli-$TS.tar.gz.age ($(stat -c %s "$OUT/signal-cli-$TS.tar.gz.age") bytes, $(ls "$OUT"/signal-cli-*.age | wc -l) kept)"
