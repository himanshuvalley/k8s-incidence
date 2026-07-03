FROM node:20-alpine
WORKDIR /app
COPY services/gateway/package.json ./
RUN npm install --production
COPY common ./common
COPY services/gateway/server.js ./server.js
EXPOSE 8080
CMD ["node", "server.js"]
