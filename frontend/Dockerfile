# HireIQ frontend: build the React app, then serve the static files with an unprivileged nginx.
# The API address is baked in at BUILD time (Vite reads VITE_* variables while building):
#   docker compose build --build-arg VITE_API_BASE_URL=https://api.example.com frontend
# Only public values belong here. NEVER pass API keys or the manager token.

FROM node:20-alpine AS build
WORKDIR /app
# The repository ships no package-lock.json, so `npm install` is used (see docs/DEPLOYMENT_GUIDE.md, "Known gaps").
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY . .
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
# `npm run build` = type-check (tsc) + vite build; the build fails on any TypeScript error.
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
