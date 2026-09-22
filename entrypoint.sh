#!/bin/sh
# settings.json
if [ -d /app/settings.json ]; then
    echo "ERROR: settings.json is a directory. On host: rm -rf data/settings.json && echo '{}' > data/settings.json"
    exit 1
fi
if [ ! -f /app/settings.json ]; then
    echo '{}' > /app/settings.json
fi

# library.db
if [ -d /app/library.db ]; then
    echo "ERROR: library.db is a directory. On host: rm -rf data/library.db && touch data/library.db"
    exit 1
fi
if [ ! -f /app/library.db ]; then
    touch /app/library.db
fi

exec "$@"
