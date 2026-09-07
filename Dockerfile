# 1) Siteyi üret
FROM python:3.12-slim AS derleyici
WORKDIR /src
RUN pip install --no-cache-dir jinja2
COPY build/ build/
COPY templates/ templates/
COPY static/ static/
COPY data/ data/
RUN python build/derle.py

# 2) Yayınla
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=derleyici /src/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
