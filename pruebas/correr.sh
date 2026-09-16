#!/bin/bash
# Corre las 37 suites de Mástil. Desde Git Bash:
#     bash pruebas/correr.sh
#
# Son deterministas: reloj falso, Telegram y Gemini dobles, base temporal que
# se borra sola. No tocan la VM, ni el bot real, ni produccion.
D="$(cd "$(dirname "$0")" && pwd)"
cd "$D/.." || exit 1
TOTAL=0
FALLARON=0
for f in "$D"/test_*.py; do
    nombre=$(basename "$f" .py)
    salida=$(python -X utf8 "$f" 2>&1)
    codigo=$?
    ok=$(echo "$salida" | grep -cE '^  ok ')
    TOTAL=$((TOTAL + ok))
    printf "%-24s exit=%s ok=%s\n" "$nombre" "$codigo" "$ok"
    if [ "$codigo" != "0" ]; then
        FALLARON=$((FALLARON + 1))
        echo "$salida" | grep MAL | head -5
    fi
done
echo "----------------------------------------"
echo "TOTAL: $TOTAL aserciones | suites con fallas: $FALLARON"
