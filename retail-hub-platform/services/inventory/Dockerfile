FROM node:20-alpine
WORKDIR /app
COPY services/inventory/package.json ./
RUN npm install --production
COPY common ./common
COPY services/inventory/server.js ./server.js
EXPOSE 5003
CMD ["node", "server.js"]
