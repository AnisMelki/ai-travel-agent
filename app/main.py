import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.agent.bootstrap import BootstrapApplication
from app.core.config import configure_logging
from app.handlers.http_error_handlers import register_exception_handlers
from app.router.flight_router import router as flight_router

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logging.getLogger(__name__).info("Starting up application")
    bootstrap_app = BootstrapApplication()
    await bootstrap_app.startup(app)
    yield
    logging.getLogger(__name__).info("Shutting down application")
    await bootstrap_app.shutdown()


app = FastAPI(title="Flight API", version="1.0.0", lifespan=lifespan, docs_url=None)
app.include_router(flight_router)
register_exception_handlers(app)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def chat_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui() -> HTMLResponse:
    return HTMLResponse(
        """
        <!DOCTYPE html>
        <html>
        <head>
            <link
                rel="stylesheet"
                href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"
            >
        </head>

        <body>
            <div id="swagger-ui"></div>

            <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>

            <script>
                SwaggerUIBundle({
                    url: "/openapi.json",
                    dom_id: "#swagger-ui",

                    requestInterceptor: (request) => {
                        const conversationId =
                            localStorage.getItem("conversation_id");

                        if (conversationId) {
                            request.headers["X-Conversation-ID"] =
                                conversationId;
                        }

                        return request;
                    },

                    responseInterceptor: (response) => {
                        const conversationId =
                            response.headers["x-conversation-id"];

                        if (conversationId) {
                            localStorage.setItem(
                                "conversation_id",
                                conversationId
                            );
                        }
                        return response;
                    }
                });
            </script>
        </body>
        </html>
        """
    )
