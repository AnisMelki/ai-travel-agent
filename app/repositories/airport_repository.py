from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession as Session

from app.model.airport import AirportModel


class AirportRepository:
    """
    Repository responsible for querying airports from the database.

    This class only performs data access.
    It does not contain business logic or raise domain exceptions.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    async def find_by_city(self, city: str) -> list[str]:
        """
        Return all airports whose city exactly matches the given city
        (case-insensitive).

        Example:
            Montreal -> [YUL]
            London -> [LHR, LGW, LCY, STN, LTN]
        """
        normalized_city = city.strip().lower()

        statement = (
            select(AirportModel.iata_code)
            .where(func.lower(AirportModel.city) == normalized_city)
            .order_by(AirportModel.iata_code)
        )

        return list(await self._session.scalars(statement))

    async def search(self, value: str) -> list[str]:
        """
        Fallback search.

        Searches by:
        - IATA code
        - city
        - airport name

        Intended for fuzzy matching when an exact city lookup
        returns no results.
        """
        normalized = value.strip().lower()

        statement = (
            select(AirportModel.iata_code)
            .where(
                or_(
                    func.lower(AirportModel.iata_code) == normalized,
                    func.lower(AirportModel.city).contains(normalized),
                    func.lower(AirportModel.airport_name).contains(normalized),
                )
            )
            .order_by(
                AirportModel.city,
                AirportModel.airport_name,
            )
        )

        return list(await self._session.scalars(statement))
