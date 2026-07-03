FROM node:20-alpine
WORKDIR /app
COPY services/analytics/package.json ./
RUN npm install --production
COPY common ./common
COPY services/analytics/server.js ./server.js
EXPOSE 5004
CMD ["node", "server.js"]
