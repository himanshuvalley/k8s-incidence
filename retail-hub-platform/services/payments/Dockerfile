FROM node:20-alpine
WORKDIR /app
COPY services/payments/package.json ./
RUN npm install --production
COPY common ./common
COPY services/payments/server.js ./server.js
EXPOSE 5005
CMD ["node", "server.js"]
