"""notify 出入参"""

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: str
    level: str
    title: str
    body: str
    read: bool
    createdAt: str


class UnreadOut(BaseModel):
    count: int
