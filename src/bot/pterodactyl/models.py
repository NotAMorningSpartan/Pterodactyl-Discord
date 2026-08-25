from typing import Literal

from pydantic import BaseModel

PowerAction = Literal["start", "restart", "stop", "kill"]
PowerState = Literal["running", "starting", "stopping", "offline"]


class Server(BaseModel):
    id: int
    identifier: str
    name: str
    node: int


class ResourceUsage(BaseModel):
    current_state: PowerState
    is_suspended: bool
    memory_bytes: int
    memory_limit_bytes: int
    cpu_absolute: float
    disk_bytes: int
    network_rx_bytes: int
    network_tx_bytes: int
    uptime: int  # milliseconds
