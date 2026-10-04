#!/bin/sh
# Русификатор Final Fantasy (PSP) для Linux и macOS.
# Запуск: ./rusify.sh "Final Fantasy [USA].iso"
#   или без аргументов, если образ лежит в этой же папке.
DIR=$(cd "$(dirname "$0")" && pwd)
for PY in python3 python; do
    if command -v "$PY" >/dev/null 2>&1 && \
       "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
        exec "$PY" "$DIR/ff1_rus.py" "$@"
    fi
done
echo "Не найден Python 3.8 или новее."
echo "Linux: установите пакет python3 (например: sudo apt install python3)."
echo "macOS: установите Python с https://www.python.org/downloads/"
exit 1
