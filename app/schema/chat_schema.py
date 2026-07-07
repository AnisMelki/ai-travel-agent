from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., description="The message to be sent to the chatbot")


class ChatResponse(BaseModel):
    response: str
