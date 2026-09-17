# Test Web Interface: сборка Vite и раздача статики через nginx.
#
# Сборка выполняется из корня проекта:
#   docker build -f docker/frontend.Dockerfile -t shin-frontend .

# ---------------------------------------------------------------- сборка

FROM node:20-alpine AS build

WORKDIR /app

# Зависимости отдельным слоем — переиспользуется, пока не менялся lock-файл.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# Vite подставляет переменные окружения в бандл НА ЭТАПЕ СБОРКИ, а не при
# запуске контейнера. Поэтому адрес API фиксируется здесь.
#
# Значение `/api` выбрано намеренно. Браузер работает на машине пользователя
# и не видит внутреннюю сеть Docker: адрес вроде `http://backend:8000`
# оттуда не резолвится. Относительный путь уходит на тот же origin, где
# лежит страница, а nginx проксирует его на backend. Заодно снимается
# вопрос CORS: запрос становится одноисточниковым.
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# ---------------------------------------------------------------- рантайм

FROM nginx:alpine AS runtime

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD wget --quiet --spider http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
