"""Import airport data from data/world_airports.csv into the airports table.

Run directly, e.g.:
    python "app/script.py/import_airports.py"
"""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

# Allow running this file directly (its containing directory is not a valid
# dotted package name, so we add the project root to sys.path ourselves).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # noqa: E402

from app.database.base import Base  # noqa: E402
from app.database.session import SessionLocal, engine  # noqa: E402
from app.model.airport import AirportModel  # noqa: E402

CSV_PATH = PROJECT_ROOT / "app" / "data" / "world_airports.csv"
BATCH_SIZE = 500


def read_airports(csv_path: Path) -> list[dict[str, object]]:
    with csv_path.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        return [
            {
                "iata_code": row["IATA_CODE"].strip(),
                "airport_name": row["AIRPORT"].strip(),
                "city": row["CITY"].strip(),
                "country": row["COUNTRY"].strip(),
                "latitude": float(row["LATITUDE"]),
                "longitude": float(row["LONGITUDE"]),
            }
            for row in reader
            if row["IATA_CODE"].strip()
        ]


async def import_airports(
    csv_path: Path = CSV_PATH, batch_size: int = BATCH_SIZE
) -> int:
    airports = read_airports(csv_path)
    if not airports:
        return 0

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        for start in range(0, len(airports), batch_size):
            batch = airports[start : start + batch_size]

            stmt = sqlite_insert(AirportModel).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=[AirportModel.iata_code],
                set_={
                    "airport_name": stmt.excluded.airport_name,
                    "city": stmt.excluded.city,
                    "country": stmt.excluded.country,
                    "latitude": stmt.excluded.latitude,
                    "longitude": stmt.excluded.longitude,
                },
            )
            await session.execute(stmt)

        await session.commit()

    return len(airports)


if __name__ == "__main__":
    imported_count = asyncio.run(import_airports())
    print(f"Imported {imported_count} airports into the 'airports' table.")
