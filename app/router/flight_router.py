from agents import Runner
from app.schema.chat_schema import ChatRequest
from fastapi import APIRouter, Request
import json

router = APIRouter(prefix="/flight", tags=["flight"])


@router.post("/chat")
async def chat_with_flight_agent(request: Request, chat_request: ChatRequest):
    flight_agent = request.app.state.flight_agent
    response = await Runner.run(flight_agent, chat_request.message)
    return {
        "response": response.final_output.model_dump(),
        "debug_item": [str(item) for item in response.new_items],
    }
