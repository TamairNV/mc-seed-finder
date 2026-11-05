FROM python:3.12-slim AS native
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev git ca-certificates \
    && git clone https://github.com/Cubitect/cubiomes.git /src/cubiomes \
    && git -C /src/cubiomes checkout e61f905
COPY native/seedlib.c /src/seedlib.c
RUN cd /src/cubiomes && gcc -O3 -fwrapv -shared -fPIC -I. /src/seedlib.c \
    biomenoise.c biomes.c finders.c generator.c layers.c noise.c quadbase.c util.c \
    -lm -lpthread -o /opt/seedlib.so

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SEEDLIB_PATH=/opt/seedlib.so
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=native /opt/seedlib.so /opt/seedlib.so
COPY app ./app

FROM base AS test
ENV PYTHONPATH=/app
RUN pip install --no-cache-dir pytest==8.3.* httpx==0.27.*
COPY tests ./tests

FROM base AS app
EXPOSE 8000
CMD ["uvicorn", "app.main:default_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
