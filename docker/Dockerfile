FROM python:3.14-slim

WORKDIR /app

ENV KIVY_CALENDAR_DB_PATH=/data/kivy_calendar.db

RUN mkdir -p /data

COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/src ./backend/src

RUN pip install --no-cache-dir ./backend

VOLUME ["/data"]

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
