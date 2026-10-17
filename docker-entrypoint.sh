#!/bin/bash
set -e

# Wait for database to be ready
DB_HOST="${POSTGRES_HOST:-shizuha-db}"
DB_PORT="${POSTGRES_PORT:-5432}"
echo "Waiting for database at $DB_HOST:$DB_PORT..."
while ! nc -z "$DB_HOST" "$DB_PORT"; do
  sleep 0.1
done
echo "Database started"

# Install shared storage package if mounted
if [ -d /packages/shizuha-storage ]; then
  echo "Installing shizuha-storage package..."
  pip install -e /packages/shizuha-storage --quiet
fi

# Create database if it doesn't exist using Django management command
echo "Creating database if it doesn't exist..."
python manage.py createdb

# Run migrations
echo "Running migrations..."
python manage.py migrate --noinput

# Local administrative accounts are an explicit operator action. Never create
# an administrator or assign a preset password while starting an image.

# Collect static files for nginx to serve
echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Setup complete. Starting services with supervisord..."

# Execute the main command (supervisord)
exec "$@"
