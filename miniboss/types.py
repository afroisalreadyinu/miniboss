from pathlib import Path
from typing import Union, Iterable

import attr
from attr.validators import instance_of, deep_iterable
from slugify import slugify

from miniboss.exceptions import MinibossException

@attr.s(kw_only=True)
class Network:
    name: str = attr.ib(validator=instance_of(str))
    id: str = attr.ib(validator=instance_of(str))

@attr.s(kw_only=True)
class Options:
    network: Network = attr.ib(validator=instance_of(Network))
    timeout: Union[float, int] = attr.ib(validator=instance_of((float, int)))
    remove: bool = attr.ib(validator=instance_of(bool))
    run_dir: str = attr.ib(validator=instance_of(str))
    build: Iterable[str] = attr.ib(validator=deep_iterable(member_validator=instance_of(str)))

class AgentStatus:
    NULL = 'null'
    IN_PROGRESS = 'in-progress'
    STARTED = 'started'
    FAILED = 'failed'
    STOPPED = 'stopped'

class RunCondition:
    # Actions
    CREATE = 'create'
    START = 'start'
    PRE_START = 'pre-start'
    POST_START = 'post-start'
    PING = 'ping'
    # States
    NULL = 'null'
    BUILD_IMAGE = 'build-image'
    STARTED = 'started'
    RUNNING = 'running'
    FAILED = 'failed'

    def __init__(self) -> None:
        self.actions: list[str] = []
        self.state = self.NULL

    def already_running(self) -> None:
        self.state = self.RUNNING

    def pinged(self) -> None:
        self.actions.append(self.PING)
        self.state = self.RUNNING

    def pre_started(self) -> None:
        self.actions.append(self.PRE_START)

    def post_started(self) -> None:
        self.actions.append(self.POST_START)

    def build_image(self) -> None:
        self.actions.append(self.BUILD_IMAGE)

    def started(self) -> None:
        self.state = self.STARTED
        self.actions.append(self.START)

    def fail(self) -> None:
        self.state = self.FAILED

class Actions:
    START = 'start'
    STOP = 'stop'

group_name: Union[str, None] = None

def update_group_name(maindir: str) -> str:
    global group_name
    if group_name is None:
        group_name = slugify(Path(maindir).name)
    return group_name

def set_group_name(name: str) -> None:
    global group_name
    if group_name is not None:
        raise MinibossException("Group name has already been set, it cannot be changed")
    group_name = name

def _unset_group_name() -> None:
    global group_name
    group_name = None
