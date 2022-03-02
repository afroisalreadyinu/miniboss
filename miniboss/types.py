from pathlib import Path

import attr
from attr.validators import instance_of, deep_iterable
from slugify import slugify

from miniboss.exceptions import MinibossException

@attr.s(kw_only=True)
class Network:
    name = attr.ib(validator=instance_of(str))
    id = attr.ib(validator=instance_of(str))

@attr.s(kw_only=True)
class Options:
    network = attr.ib(validator=instance_of(Network))
    timeout = attr.ib(validator=instance_of((float, int)))
    remove = attr.ib(validator=instance_of(bool))
    run_dir = attr.ib(validator=instance_of(str))
    build = attr.ib(validator=deep_iterable(member_validator=instance_of(str)))

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

    def __init__(self):
        self.actions = []
        self.state = self.NULL

    def already_running(self):
        self.state = self.RUNNING

    def pinged(self):
        self.actions.append(self.PING)
        self.state = self.RUNNING

    def pre_started(self):
        self.actions.append(self.PRE_START)

    def post_started(self):
        self.actions.append(self.POST_START)

    def build_image(self):
        self.actions.append(self.BUILD_IMAGE)

    def started(self):
        self.state = self.STARTED
        self.actions.append(self.START)

    def fail(self):
        self.state = self.FAILED

class Actions:
    START = 'start'
    STOP = 'stop'

group_name = None

def update_group_name(maindir):
    global group_name
    if group_name is None:
        group_name = slugify(Path(maindir).name)
    return group_name

def set_group_name(name):
    global group_name
    if group_name is not None:
        raise MinibossException("Group name has already been set, it cannot be changed")
    group_name = name

def _unset_group_name():
    global group_name
    group_name = None
