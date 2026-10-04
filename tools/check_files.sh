#!/bin/sh
# Проверка, что в репозиторий не попали файлы игры и прочее лишнее.
#   sh tools/check_files.sh            - все файлы в git
#   sh tools/check_files.sh ФАЙЛ...    - только указанные
# Двоичные файлы допускаются только как шрифты перевода
# (translation/fonts/*/*.FIF и *.GIM), любой файл - не больше 1 МБ.
cd "$(dirname "$0")/.." || exit 2
if [ $# -gt 0 ]; then printf '%s\n' "$@"; else git ls-files; fi | {
    bad=0
    while IFS= read -r f; do
        [ -f "$f" ] || continue
        case "$f" in
            *.[iI][sS][oO]|*.[cC][sS][oO]|*.[zZ][sS][oO]|*.[dD][pP][kK]|*.[pP][cC][kK]|*.[pP][bB][pP]|*.[pP][pP][sS][tT])
                echo "лишнее: $f - файл игры или эмулятора"; bad=1; continue ;;
        esac
        size=$(wc -c < "$f")
        if [ "$size" -gt 1048576 ]; then
            echo "лишнее: $f - слишком большой файл ($size байт)"; bad=1
        fi
        if [ -s "$f" ] && ! grep -qI '' "$f"; then
            case "$f" in
                translation/fonts/*/*.FIF|translation/fonts/*/*.GIM) ;;
                *) echo "лишнее: $f - двоичный файл вне translation/fonts"; bad=1 ;;
            esac
        fi
    done
    [ $bad -eq 0 ] && echo "Лишних файлов нет."
    exit $bad
}
