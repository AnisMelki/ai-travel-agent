import asyncio

from sqlalchemy import select

from app.database.session import SessionLocal
from app.model.airport import AirportModel


async def main() -> None:
    async with SessionLocal() as session:
        result = await session.scalars(select(AirportModel).limit(10))
        airports = result.all()

        for airport in airports:
            print(
                airport.iata_code,
                airport.city,
                airport.airport_name,
            )


if __name__ == "__main__":
    asyncio.run(main())
