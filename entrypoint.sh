#!/bin/sh
# Ensure settings.json exists as a file (not a directory) before starting.
# This handles the case where Docker creates it as a dir on first bind-mount.
if [ ! -f /app/settings.json ]; then
    echo '{}' > /app/settings.json
fi
exec "$@"
