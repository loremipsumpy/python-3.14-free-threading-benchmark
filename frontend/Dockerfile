# Static frontend: server built 100% with Node 24 builtins (zero npm).
# Official slim image (Debian): the base already ships the full runtime, so there is no
# `npm install` or package.json - same zero-dependency philosophy as the backend.
FROM node:24-slim

WORKDIR /app

COPY server.mjs ./
COPY public/ ./public/

# server.listen(port) (no host) listens on all interfaces (0.0.0.0/::), so the container
# is reachable from the host via the published port.
EXPOSE 5500

# Run as the non-root user included in the official image.
USER node

CMD ["node", "server.mjs"]
