#!/bin/sh
set -e

# If this is a fresh container with no React app yet, create one
if [ ! -f "/app/vite.config.js" ] && [ ! -f "/app/vite.config.ts" ]; then
    echo "No Vite project found — creating React app with Vite..."

    # Move to /tmp so Vite doesn't treat the path as relative to /app
    cd /tmp
    npm create vite@latest bucket-chart-ui -- --template react

    # Copy everything including hidden files into /app
    cp -r /tmp/bucket-chart-ui/. /app/
    rm -rf /tmp/bucket-chart-ui

    # Move back to /app and install dependencies
    cd /app
    npm install
    echo "React app created successfully."
else
    cd /app
    # App already exists — just install any missing dependencies
    if [ ! -d "node_modules" ]; then
        echo "Installing dependencies..."
        npm install
    fi
fi

# Start the Vite dev server, binding to 0.0.0.0 so it's
# accessible from outside the container at localhost:5173
echo "Starting Vite dev server..."
cd /app
npm run dev -- --host 0.0.0.0