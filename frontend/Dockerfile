FROM node:22-alpine AS dependencies
WORKDIR /app
COPY package.json ./
RUN npm install

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN npm run build
USER node
EXPOSE 3000
CMD ["npm", "run", "start"]
