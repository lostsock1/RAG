from pydantic import BaseModel


class RequestContext(BaseModel):
    tenant_id: str
    user_id: str
    group_ids: list[str]
    roles: list[str]
    scopes: list[str]
