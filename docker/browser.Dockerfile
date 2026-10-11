ARG NODE_IMAGE=node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392
ARG BROWSER_IMAGE=mcr.microsoft.com/playwright:v1.63.0-noble@sha256:eff16c30e6f3f4af0a03fa4b706120d5e9b0891c344a27d64559aff5900a4a27
FROM ${NODE_IMAGE} AS dependencies
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts --no-fund --no-audit

FROM ${BROWSER_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app/web
COPY --from=dependencies /build/web/node_modules/ node_modules/
COPY web/package.json web/package-lock.json web/playwright.config.ts ./
COPY web/e2e/ e2e/
COPY web/scripts/ scripts/
ENV HOME=/tmp
CMD ["npm", "run", "test:e2e"]
