#!/bin/bash
# Start Frontend Development Server

cd "$(dirname "$0")/frontend"

echo "🚀 Starting Lawn Segmentation Frontend..."
echo "📍 Directory: $(pwd)"

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "📦 Installing dependencies..."
    npm install
fi

# Start Vite dev server
echo "🌐 Starting Vite dev server on http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop the server"
echo "─────────────────────────────────────────"

npm run dev

