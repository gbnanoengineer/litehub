#!/bin/sh
export PYTHONPATH=/app/lib/tessera-deps${PYTHONPATH:+:$PYTHONPATH}
exec python3 /app/lib/tessera/tessera.py "$@"
