from pydantic import BaseModel, Field, ConfigDict


class Quotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    partner_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    quantity: float = Field(gt=0, le=1000, allow_inf_nan=False)
    unit_price: float = Field(ge=0, le=100000, allow_inf_nan=False)
