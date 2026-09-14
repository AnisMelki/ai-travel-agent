import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.agent.bootstrap import BootstrapApplication
from app.core.config import configure_logging
from app.handlers.http_error_handlers import register_exception_handlers
from app.router.flight_router import router as flight_router


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
