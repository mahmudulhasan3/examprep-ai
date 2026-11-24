#!/bin/sh
set -e

# Create any missing tables first when asked to. It is safe to run on every start,
# because it only adds tables that do not exist yet.
if [ "$INIT_DB_ON_START" = "true" ]; then
    echo "Creating database tables if they are missing..."
    python -m app.db.init_db
fi

exec "$@"