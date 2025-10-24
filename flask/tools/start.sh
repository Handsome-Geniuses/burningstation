#!/bin/sh
cd /app/tools
python -u ./isrunning.py
if [ $? -eq 0 ]; then
    echo "already running"
else
    cd /app
    echo "starting"
    PYTHONPATH=/app python -u app.py --host=0.0.0.0 --port=8011
fi