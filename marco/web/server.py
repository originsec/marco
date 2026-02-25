"""FastAPI application factory and server startup."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .routes import configure, router
from .state import AnalysisState
from .websocket import ConnectionManager

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(config: dict[str, Any] | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="marco", docs_url=None, redoc_url=None)

    state = AnalysisState()
    manager = ConnectionManager()

    effective_config = config or {}
    configure(state, manager, effective_config)

    app.include_router(router)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        try:
            # Send current state snapshot on connect
            await websocket.send_json(state.get_snapshot())
            # Keep connection alive, listen for client messages
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception:
            manager.disconnect(websocket)

    # Mount static files last so API routes take priority
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app


def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
    config: dict[str, Any] | None = None,
) -> None:
    """Start the uvicorn server."""
    import uvicorn

    app = create_app(config)

    if open_browser:
        import threading
        import time
        import webbrowser

        def _open():
            time.sleep(1.0)
            webbrowser.open(f"http://{host if host != '0.0.0.0' else 'localhost'}:{port}")

        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")
