#!/bin/bash

cd "$(dirname "$0")"
echo " Working directory: $(pwd)"

# Check if main.py exists
if [ ! -f "main.py" ]; then
    echo " Error: main.py not found!"
    exit 1
fi

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo " Activating virtual environment..."
    source venv/bin/activate
fi

# Install requirements if needed
pip install -q fastapi uvicorn yt-dlp python-multipart

echo " Opening browser in 2 seconds..."
(sleep 2 && xdg-open http://127.0.0.1:8000) &

echo " Starting server on http://127.0.0.1:8000"
echo " Press Ctrl+C to stop"

# Run the server
python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
