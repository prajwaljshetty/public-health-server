
from pydantic import BaseModel, Field
from typing import Annotated, Literal, Union

# Models
from app.models.coordinate import Coordinate


class ConstantRewardPolicy(BaseModel):
    type: Literal["constant"]
    point: int = Field(ge=0)


class RelativeRewardPolicy(BaseModel):
    type: Literal["relative"]
    base_address: Coordinate
    min_point: int = Field(ge=0)


RewardPolicy = Annotated[
    Union[ConstantRewardPolicy, RelativeRewardPolicy],
    Field(discriminator="type")
]


class AdminRegister(BaseModel):
    email: str
    password: str = Field(min_length=8)
    reward_policy: RewardPolicy

class AdminLogin(BaseModel):
    email: str
    password: str = Field(min_length=8)
