from agents import Agent, ModelSettings
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from app.schema.state_conversation import FlightRequestPatch
from app.schema.flight_schema import DecisionFlights

template_dir = Path(__file__).parent.parent / "template"

env = Environment(
    loader=FileSystemLoader(template_dir),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_prompt(template_name: str, **kwargs) -> str:
    template = env.get_template(template_name)
    return template.render(**kwargs)


def create_flight_agent(model):
    return Agent(
        name="FlightAgent",
        instructions=render_prompt("prompt_agent_flights.jinja2"),
        model=model,
        tools=[],
        output_type=FlightRequestPatch,
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
