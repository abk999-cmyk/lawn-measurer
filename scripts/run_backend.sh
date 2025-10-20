#!/bin/bash

# Lawn Analysis Backend Startup Script
# Starts the FastAPI server with proper environment setup

set -e  # Exit on error

echo "🌱 Starting Lawn Analysis Backend..."

# Get the project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"

echo "📂 Project root: $PROJECT_ROOT"
echo "📂 Backend dir: $BACKEND_DIR"

# Check if port 8000 is already in use
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "⚠️  Port 8000 is already in use!"
    echo "🔪 Killing process on port 8000..."
    lsof -ti:8000 | xargs kill -9 2>/dev/null || true
    sleep 2
fi

# Activate virtual environment
if [ -d "$PROJECT_ROOT/.venv311" ]; then
    echo "🐍 Activating Python 3.11 virtual environment..."
    source "$PROJECT_ROOT/.venv311/bin/activate"
elif [ -d "$PROJECT_ROOT/venv" ]; then
    echo "🐍 Activating virtual environment..."
    source "$PROJECT_ROOT/venv/bin/activate"
else
    echo "❌ No virtual environment found!"
    echo "Please create one with: python3 -m venv .venv311"
    exit 1
fi

# Change to backend directory
cd "$BACKEND_DIR"

# Check if dependencies are installed
if ! python -c "import fastapi" 2>/dev/null; then
    echo "📦 Installing dependencies..."
    pip install -r requirements.txt
fi

# Create necessary directories
mkdir -p logs outputs tile_cache

# Start the server
echo "🚀 Starting FastAPI server on http://localhost:8000"
echo "📊 API docs available at http://localhost:8000/docs"
echo "🛑 Press Ctrl+C to stop the server"
echo ""

python app.py

