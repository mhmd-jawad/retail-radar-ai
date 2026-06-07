FROM node:20-alpine AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

ARG VITE_DATA_MODE=eep-live
ARG VITE_API_BASE_URL=/api
ARG VITE_IE1_BASE_URL=/ie1
ARG VITE_IE2_BASE_URL=/ie2
ARG VITE_IE3_BASE_URL=/ie3
ARG VITE_API_KEY=
ARG VITE_GRAFANA_URL=

ENV VITE_DATA_MODE=$VITE_DATA_MODE
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_IE1_BASE_URL=$VITE_IE1_BASE_URL
ENV VITE_IE2_BASE_URL=$VITE_IE2_BASE_URL
ENV VITE_IE3_BASE_URL=$VITE_IE3_BASE_URL
ENV VITE_API_KEY=$VITE_API_KEY
ENV VITE_GRAFANA_URL=$VITE_GRAFANA_URL

RUN npm run build

FROM nginx:1.27-alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
