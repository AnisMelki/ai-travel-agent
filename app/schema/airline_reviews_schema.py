from pydantic import BaseModel, Field


class AirlineReview(BaseModel):
    rating: int | None = Field(default=None, description="Rating of the airline review")
    date_published: str | None = Field(
        default=None, description="Date when the review was published"
    )
    is_verified: bool | None = Field(
        default=None, description="Indicates if the review is verified"
    )
    country: str | None = Field(default=None, description="Country of the reviewer")
    comment: str | None = Field(default=None, description="Comment of the review")
    title: str | None = Field(default=None, description="Title of the review")
    name: str | None = Field(default=None, description="Name of the reviewer")


class AirlineReviewResponse(BaseModel):
    reviews: dict[str, list[AirlineReview]] = Field(
        default_factory=dict, description="List of airline reviews"
    )


class AirlineSummary(BaseModel):
    average_rating: float | None = Field(
        default=None, description="Average rating of the airline"
    )
    average_verification_rate: float | None = Field(
        default=None, description="Average verification rate of the airline"
    )

    total_comments: list[str] | None = Field(
        default=None, description="Total of comments for the airline"
    )
