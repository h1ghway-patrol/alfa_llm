from typing import Annotated

from pydantic import BaseModel, Field, HttpUrl
from pydantic.functional_validators import BeforeValidator


def strip_whitespace(value):
    if isinstance(value, str):
        return value.strip()
    return value

def clean_additional_info(value):
    if value is None:
        return None

    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned == "":
            return None
        return cleaned

    return value


NonEmptyStr = Annotated[
    str,
    BeforeValidator(strip_whitespace),
    Field(min_length=1, max_length=255),
]

AdditionalInfo = Annotated[
    str | None,
    BeforeValidator(clean_additional_info),
]


class Company(BaseModel):
    name: NonEmptyStr
    industry: NonEmptyStr
    website: HttpUrl
    additional_info: AdditionalInfo = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Acme Inc.",
                    "industry": "Technology",
                    "website": "https://acme.example.com",
                    "additional_info": "Leading provider of solutions.",
                }
            ]
        }
    }