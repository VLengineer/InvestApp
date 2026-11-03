# Vue-фронтенд «Анализатор новостей» (Vite dev-сервер внутри контейнера)
FROM node:24

EXPOSE 8888

WORKDIR /app

COPY package*.json ./
RUN npm install --registry=https://mirrors.cloud.tencent.com/npm/
COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]