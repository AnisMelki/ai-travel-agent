from pathlib import Path

from agents import Agent, ModelSettings, RunContextWrapper
from jinja2 import Environment, FileSystemLoader

from app.schema.flight_schema import DecisionFlights
from app.schema.state_conversation import FlightAgentResponse

template_dir = Path(__file__).parent.parent / "template"

env = Environment(
    loader=FileSystemLoader(template_dir),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_prompt(template_name: str, **kwargs) -> str:
    template = env.get_template(template_name)
    return template.render(**kwargs)


async def flight_agent_instructions(
    ctx: RunContextWrapper,
    agent: Agent,
) -> str:
    context = ctx.context

    return render_prompt(
        "prompt_agent_flights.jinja2",
        current_date=context.current_date,
        history=context.history[-8:],
    )


def create_flight_agent(model):
    return Agent(
        name="FlightAgent",
        instructions=flight_agent_instructions,
        model=model,
        tools=[],
        output_type=FlightAgentResponse,
        model_settings=ModelSettings(
            tool_choice="auto", parallel_tool_calls=False, temperature=0.0
        ),
    )


def create_flights_agent_selection(model):
    return Agent(
        name="FlightAgentSelection",
        instructions=render_prompt("prompt_selection_flight.jinja2"),
        model=model,
        tools=[],
        output_type=DecisionFlights,
        model_settings=ModelSettings(
            tool_choice="auto", parallel_tool_calls=False, temperature=0.0
        ),
    )
