# Stage 1: Build Frontend Application
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci --quiet || npm install --quiet

COPY . .
RUN npm run build

# Stage 2: Serve compiled SPA via Nginx
FROM nginx:1.25-alpine

# Install the http-level settings before the server configuration.  Rate-limit
# zones must live in nginx.conf, not in a virtual-host file.
COPY nginx-main.conf /etc/nginx/nginx.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy static assets to Nginx web root
COPY --from=builder /app/dist/frontend/ /usr/share/nginx/html/

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
