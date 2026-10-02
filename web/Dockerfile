FROM node:26-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# NEXT_PUBLIC_* values are inlined at build time
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_SUPPORT_URL=
ENV NEXT_PUBLIC_SUPPORT_URL=$NEXT_PUBLIC_SUPPORT_URL
ARG NEXT_PUBLIC_ERROR_REPORTING=false
ENV NEXT_PUBLIC_ERROR_REPORTING=$NEXT_PUBLIC_ERROR_REPORTING
RUN npm run build

FROM node:26-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
