"""Shared contracts: the requirements summary and the API spec.

Every agent reads and writes these. Change them only with team agreement.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field as PField

FieldType = Literal["str", "int", "float", "bool", "date", "datetime", "email"]
Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
Access = Literal["public", "user", "admin"]


class Requirements(BaseModel):
    """What the user wants, in plain words. Output of the requirements agent."""
    project_name: str
    description: str
    users: list[str]          # who uses the system, e.g. "patients", "clinic staff"
    data: list[str]           # things to store, e.g. "patients with name, phone"
    actions: list[str]        # what users can do, e.g. "patients book appointments"
    rules: list[str] = []     # business rules, e.g. "no double booking"


class Field(BaseModel):
    name: str                 # snake_case
    type: FieldType
    required: bool = True
    unique: bool = False
    read_only: bool = False   # set by the server, never accepted in request bodies
    description: str = ""


class Entity(BaseModel):
    name: str                 # PascalCase, singular, e.g. "Appointment"
    description: str = ""
    fields: list[Field]       # "id" is implicit, do not list it
    belongs_to: list[str] = []  # referenced entity names; each needs an int field <entity_snake>_id in fields


class Endpoint(BaseModel):
    method: Method
    path: str                 # e.g. "/appointments/{id}"
    summary: str
    entity: Optional[str] = None
    access: Access = "user"
    request_fields: list[str] = []   # field names accepted in the body
    status_code: int = 200


class Spec(BaseModel):
    """The API spec. Output of the architect agent, input to the coder."""
    project_name: str
    description: str
    roles: list[str] = PField(default_factory=lambda: ["user", "admin"])
    entities: list[Entity]
    endpoints: list[Endpoint]
    rules: list[str] = []     # business rules the coder must enforce
