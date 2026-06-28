# Stage 1: Build stage
FROM node:18-alpine AS build

WORKDIR /app

# Copy package descriptors and install dependencies
COPY package.json ./
RUN npm install

# Copy config and source files
COPY tsconfig.json ./
COPY app.ts ./
COPY services/ ./services/
COPY features/ ./features/

# Compile TypeScript
RUN npm run build

# Stage 2: Serve stage
FROM nginx:alpine

# Copy custom nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy static index file
COPY index.html /usr/share/nginx/html/

# Copy compiled JavaScript files and templates from build stage
COPY --from=build /app/app.js /usr/share/nginx/html/
COPY --from=build /app/app.js.map /usr/share/nginx/html/
COPY --from=build /app/services/ /usr/share/nginx/html/services/
COPY --from=build /app/features/ /usr/share/nginx/html/features/

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
