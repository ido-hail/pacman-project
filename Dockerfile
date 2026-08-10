FROM node:22-bookworm-slim

WORKDIR /usr/src/app

# Allow the built-in non-root node user to own the application directory
RUN chown node:node /usr/src/app

# Copy dependency manifests first to maximize Docker layer caching
COPY --chown=node:node package.json package-lock.json ./

USER node

# Install only production dependencies using the lock file
RUN npm ci --omit=dev && npm cache clean --force

# Copy application source
COPY --chown=node:node . .

EXPOSE 8080

CMD ["npm", "start"]
