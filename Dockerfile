FROM node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436

WORKDIR /usr/src/app

# Allow the built-in non-root node user to own the application directory
RUN chown node:node /usr/src/app

# Copy dependency manifests first to maximize Docker layer caching
COPY --chown=node:node package.json package-lock.json ./

USER node

# Install only production dependencies using the lock file
RUN npm ci --omit=dev && npm cache clean --force

USER root

# npm is required only during build. Remove it from the runtime image to
# reduce unnecessary packages and vulnerability surface.
RUN rm -rf \
    /usr/local/lib/node_modules/npm \
    /usr/local/bin/npm \
    /usr/local/bin/npx

# Copy application source
COPY --chown=node:node . .

USER node

EXPOSE 8080

CMD ["node", "."]
