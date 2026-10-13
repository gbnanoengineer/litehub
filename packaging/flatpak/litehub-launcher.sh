#!/bin/sh
export PYTHONPATH=/app/lib/litehub-deps${PYTHONPATH:+:$PYTHONPATH}
exec python3 /app/lib/litehub/litehub.py "$@"
