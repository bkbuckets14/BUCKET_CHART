FROM node:20-slim

WORKDIR /app

# Copy package files if they exist (will be skipped on first boot)
COPY package*.json ./

# entrypoint script handles first-time setup and starting the dev server
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 5173

ENTRYPOINT ["/docker-entrypoint.sh"]
