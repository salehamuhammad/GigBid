FROM node:22-alpine AS build
WORKDIR /web
COPY apps/web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web ./
ARG API_URL=http://api:8000
ARG NEXT_PUBLIC_FREE_PREVIEW=false
ENV API_URL=${API_URL}
ENV NEXT_PUBLIC_FREE_PREVIEW=${NEXT_PUBLIC_FREE_PREVIEW}
RUN npm run build

FROM node:22-alpine
WORKDIR /web
ENV NODE_ENV=production PORT=3000
COPY --from=build /web/.next/standalone ./
COPY --from=build /web/.next/static ./.next/static
COPY --from=build /web/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
