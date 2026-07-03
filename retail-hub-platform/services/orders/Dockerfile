FROM node:20-alpine
WORKDIR /app
COPY services/orders/package.json ./
RUN npm install --production
COPY common ./common
COPY services/orders/server.js ./server.js
EXPOSE 5001
CMD ["node", "server.js"]
