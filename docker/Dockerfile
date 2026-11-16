FROM python:3.14-slim

WORKDIR /app

ENV KIVY_CALENDAR_DB_PATH=/data/kivy_calendar.db

RUN useradd --system --no-create-home --uid 10001 app \
    && mkdir -p /data \
    && chown app:app /data

COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/src ./backend/src

RUN pip install --no-cache-dir ./backend

VOLUME ["/data"]

EXPOSE 8000

USER app

# Binding 0.0.0.0 is required inside the container; docker/compose.yml
# publishes the port on a single host IP (127.0.0.1 by default).
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
