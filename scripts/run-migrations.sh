#!/bin/sh
set -eu

echo "Running database migrations..."
exec alembic upgrade head
