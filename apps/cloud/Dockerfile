# OCI image contains application code only; never bake Doppler data into layers.
FROM node:24-trixie-slim@sha256:0820eaa85e07d0490446dd01d14707e17e6108a36988cf374899cd057eb3812d AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY tsconfig.json tsconfig.build.json ./
COPY src ./src
COPY assets ./assets
RUN npm run build && npm prune --omit=dev --ignore-scripts

FROM node:24-trixie-slim@sha256:0820eaa85e07d0490446dd01d14707e17e6108a36988cf374899cd057eb3812d AS runtime
ARG APP_REVISION=unknown
ENV APP_REVISION=${APP_REVISION}
ENV NODE_ENV=production
WORKDIR /app
COPY --chown=node:node --from=build /app/node_modules ./node_modules
COPY --chown=node:node --from=build /app/dist ./dist
COPY --chown=node:node --from=build /app/assets ./assets
COPY --chown=node:node ./db ./db
COPY --chown=node:node --from=build /app/package.json ./package.json
COPY --chown=node:node ./healthcheck.mjs ./healthcheck.mjs
# The production entrypoint invokes node directly. Keep npm in the build
# stage only; its globally bundled CLI packages are unused in production.
# Preserve the distro tar utility: it may be needed by operator tooling.
RUN rm -rf /usr/local/lib/node_modules/npm \
    /usr/local/lib/node_modules/corepack \
    /opt/yarn-v1.22.22 \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx \
    /usr/local/bin/corepack /usr/local/bin/yarn /usr/local/bin/yarnpkg
USER node
EXPOSE 8787
# Run the readiness check inside the container without downloading extra tools.
# Coolify uses the Dockerfile HEALTHCHECK in preference to its HTTP probe.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 CMD ["node", "healthcheck.mjs"]
CMD ["node","dist/main.js"]
