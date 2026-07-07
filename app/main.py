from app.agent.bootstrap import bootstrap_agent
from app.agent.flight_agent import create_flight_agent
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.router.flight_router import router as flight_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    model = bootstrap_agent()
    app.state.flight_agent = create_flight_agent(model)
    yield
    print("Shutting down application")


app = FastAPI(title="Flight API", version="1.0.0", lifespan=lifespan)
app.include_router(flight_router)
