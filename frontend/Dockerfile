# ============================================
# Plasma AI — Frontend Dockerfile
# Multi-stage build for Next.js
# ============================================

# ---------- Stage 1: Builder ----------
FROM node:20-alpine AS builder

WORKDIR /app

# Accept API URL as build argument (baked into Next.js at build time)
ARG NEXT_PUBLIC_API_URL=/api/v1
ARG BACKEND_INTERNAL_URL=http://backend:8000/api/v1
ARG PLASMA_BUILD_SHA=unknown
ARG PLASMA_BUILD_TIME=unknown
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV BACKEND_INTERNAL_URL=$BACKEND_INTERNAL_URL
ENV NEXT_PUBLIC_BUILD_SHA=$PLASMA_BUILD_SHA
ENV PLASMA_BUILD_SHA=$PLASMA_BUILD_SHA
ENV PLASMA_BUILD_TIME=$PLASMA_BUILD_TIME

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---------- Stage 2: Runner ----------
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

ARG PLASMA_BUILD_SHA=unknown
ARG PLASMA_BUILD_TIME=unknown
ARG NEXT_PUBLIC_API_URL=/api/v1
ARG BACKEND_INTERNAL_URL=http://backend:8000/api/v1
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV BACKEND_INTERNAL_URL=$BACKEND_INTERNAL_URL
ENV NEXT_PUBLIC_BUILD_SHA=$PLASMA_BUILD_SHA
ENV PLASMA_BUILD_SHA=$PLASMA_BUILD_SHA
ENV PLASMA_BUILD_TIME=$PLASMA_BUILD_TIME

# Copy only what's needed to run
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json

EXPOSE 3000

CMD ["npm", "start"]
