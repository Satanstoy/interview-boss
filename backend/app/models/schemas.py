from typing import Dict, Any
from pydantic import BaseModel


class GenericUpdateRequest(BaseModel):
    table_name: str
    record_id: int
    update_data: Dict[str, Any]
