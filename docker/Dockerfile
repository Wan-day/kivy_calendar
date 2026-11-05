FROM python:3.14-slim

WORKDIR /app

COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/src ./backend/src

RUN pip install --no-cache-dir ./backend

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
