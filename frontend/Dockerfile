FROM node:22-alpine AS base
WORKDIR /app

FROM base AS dependencies
COPY package.json ./
COPY package-lock.json ./
RUN npm ci --ignore-scripts

FROM base AS builder
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
# Standalone Next reads HOSTNAME when choosing its listening interface.  In a
# container it must bind all interfaces so Docker's healthcheck and port map
# can reach it reliably.
ENV HOSTNAME=0.0.0.0
RUN addgroup -S nextjs && adduser -S nextjs -G nextjs
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
