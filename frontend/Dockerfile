# ---- build stage ----
FROM node:22-alpine AS build
WORKDIR /app

# Dependency manifest first, so `npm ci` is cached separately from app code changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---- serve stage ----
# The built SPA is static output - no Node runtime needed to serve it.
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
