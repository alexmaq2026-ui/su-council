#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

# Terminate other active backends on Supabase to release any hanging locks
python terminate_backends.py

python manage.py collectstatic --no-input
python manage.py migrate

# Ensure all PostgreSQL sequences are synced with MAX(id)
python reset_sequences.py

echo "Build completed successfully!"
