FROM node:20-alpine
WORKDIR /app
COPY services/users/package.json ./
RUN npm install --production
COPY common ./common
COPY services/users/server.js ./server.js
EXPOSE 5002
CMD ["node", "server.js"]
