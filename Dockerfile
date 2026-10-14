# ─────────────────────────────────────────────────────────────────────────────
# Next.js 15 Multi-Stage Production Dockerfile
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Base Image ───────────────────────────────────────────────────────
FROM node:22-alpine AS base

# Install libc6-compat if needed by Alpine
RUN apk add --no-cache libc6-compat
WORKDIR /app

# ── Stage 2: Dependencies ─────────────────────────────────────────────────────
FROM base AS deps
COPY package.json package-lock.json ./
RUN npm ci

# ── Stage 3: Builder ──────────────────────────────────────────────────────────
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Environment argument for build-time
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=${BACKEND_URL}
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ── Stage 4: Production Runner (Lean Alpine Image) ────────────────────────────
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Non-root user for security compliance
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy static assets and standalone bundle from builder
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
