from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Float
from app.database.base import Base


class AirportModel(Base):
    __tablename__ = "airports"
    iata_code: Mapped[str] = mapped_column(String(3), primary_key=True)
    airport_name: Mapped[str] = mapped_column(String(100), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
