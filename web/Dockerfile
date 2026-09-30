FROM nginx:1.27-alpine

COPY web/nginx.conf /etc/nginx/conf.d/default.conf
COPY web/index.html web/technology.html web/logic.html web/tokens.html web/styles.css web/app.js web/tokens.js web/support.js /usr/share/nginx/html/

EXPOSE 8080