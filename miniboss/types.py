from typing import NamedTuple, List

# pylint: disable=inherit-non-class
class Network(NamedTuple):
    name: str
    id: str

# pylint: disable=inherit-non-class
class Options(NamedTuple):
    network: Network
    timeout: int
    remove: bool
    run_dir: str
    build: List[str]

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
