import asyncio

from sqlalchemy import select

from app.database.session import SessionLocal
from app.model.airport import AirportModel
from app.repositories.airport_repository import AirportRepository


def test_airports_table_is_populated():
    async def query():
        async with SessionLocal() as session:
            result = await session.scalars(select(AirportModel).limit(10))
            return result.all()

    airports = asyncio.run(query())

    assert len(airports) == 10
    for airport in airports:
        assert airport.iata_code
        assert airport.city
        assert airport.airport_name


def test_find_by_city_is_case_insensitive_and_returns_sorted_codes():
    async def query():
        async with SessionLocal() as session:
            return await AirportRepository(session).find_by_city("PARIS")

    codes = asyncio.run(query())

    assert codes == sorted(codes)
    assert {"CDG", "ORY"}.issubset(set(codes))


def test_find_by_city_returns_empty_list_when_no_match():
    async def query():
        async with SessionLocal() as session:
            return await AirportRepository(session).find_by_city("Nowhereville")

    assert asyncio.run(query()) == []


def test_search_matches_exact_iata_code():
    async def query():
        async with SessionLocal() as session:
            return await AirportRepository(session).search("cdg")

    assert asyncio.run(query()) == ["CDG"]


def test_search_matches_partial_airport_name():
    async def query():
        async with SessionLocal() as session:
            return await AirportRepository(session).search("orly")

    assert asyncio.run(query()) == ["ORY"]


def test_search_returns_empty_list_when_no_match():
    async def query():
        async with SessionLocal() as session:
            return await AirportRepository(session).search("zzz-no-such-airport")

    assert asyncio.run(query()) == []
