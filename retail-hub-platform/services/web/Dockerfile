FROM node:20-alpine
WORKDIR /app
COPY services/web/package.json ./
RUN npm install --production
COPY services/web/server.js ./
COPY services/web/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
