# Development Dockerfile for Shizuha Notes Frontend
FROM node:20-alpine

WORKDIR /app

# Create packages directory (will be volume-mounted in dev)
RUN mkdir -p /packages

# Install dependencies (npm install may fail for @shizuha/ui but that's ok for build step)
# The actual package will be available via volume mount at runtime
COPY package*.json ./
COPY vendor/ ./vendor/
RUN npm ci --ignore-scripts --no-audit --no-fund

# Copy source code
COPY . .

# Expose Vite dev server port
EXPOSE 80

# Start development server
CMD ["npm", "run", "dev"]
