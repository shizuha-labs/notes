FROM mcr.microsoft.com/playwright:v1.58.2-noble

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci --no-audit --no-fund

# Install Playwright browsers
RUN npx playwright install chromium

# Copy test files
COPY . .

# Default command
CMD ["npm", "test"]
