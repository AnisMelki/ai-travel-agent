from app.repositories.airport_repository import AirportRepository
from app.exception.flight_exceptions import AirportNotFoundError, AmbiguityAirportError
from app.schema.state_conversation import FlightFieldName


class AirportResolutionService:
    def __init__(self, airport_repository: AirportRepository):
        self.repository = airport_repository

    async def search_city(
        self, city: str, *, field: FlightFieldName | None = None
    ) -> str:
        normalized_city = city.strip().lower()
        iata_codes = await self.repository.find_by_city(normalized_city)
        if not iata_codes:
            iata_codes = await self.repository.search(normalized_city)

        iata_codes = sorted(set(iata_codes))  # Remove duplicates and sort the list
        if not iata_codes:
            raise AirportNotFoundError(city, field=field)
        if len(iata_codes) > 1:
            raise AmbiguityAirportError(city, iata_codes, field=field)
        return iata_codes[0]
