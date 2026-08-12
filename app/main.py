from app.agent.bootstrap import BootstrapApplication
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.router.flight_router import router as flight_router
from app.core.config import configure_logging
import logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logging.getLogger(__name__).info("Starting up application")
    bootstrap_app = BootstrapApplication()
    await bootstrap_app.startup(app)
    yield
    logging.getLogger(__name__).info("Shutting down application")
    await bootstrap_app.shutdown()


app = FastAPI(title="Flight API", version="1.0.0", lifespan=lifespan)
app.include_router(flight_router)
