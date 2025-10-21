#!/bin/bash
# Start Backend Server

cd "$(dirname "$0")/backend"

echo "🚀 Starting Lawn Segmentation Backend..."
echo "📍 Directory: $(pwd)"

# Activate virtual environment
if [ -f "../.venv311/bin/activate" ]; then
    source ../.venv311/bin/activate
    echo "✅ Virtual environment activated"
else
    echo "❌ Virtual environment not found at ../.venv311"
    echo "   Please run: python3.11 -m venv .venv311"
    exit 1
fi

# Check if model exists
if [ ! -f "model_19class.pth" ]; then
    echo "⚠️  Model file not found. It will be downloaded on first analysis (93MB)"
fi

# Start Flask server
echo "🌐 Starting Flask server on http://localhost:5000"
echo "📋 Logs will be written to logs/app.log"
echo ""
echo "Press Ctrl+C to stop the server"
echo "─────────────────────────────────────────"

python app.py

