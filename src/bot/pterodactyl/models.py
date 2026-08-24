from typing import Literal

from pydantic import BaseModel

PowerAction = Literal["start", "restart", "stop", "kill"]
PowerState = Literal["running", "starting", "stopping", "offline"]


class Server(BaseModel):
    id: int
    identifier: str
    name: str
    node: int
