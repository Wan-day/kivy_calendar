"""FastAPI application for the Kivy calendar backend."""

from fastapi import FastAPI

app = FastAPI(title="Kivy Calendar Backend")


@app.get("/health")
def health() -> dict[str, str]:
    """Return the health status of the backend."""
    return {"status": "ok"}
