import threading
import random
import time
import logging
from typing import NamedTuple

from drillmaster.docker_client import DockerClient
from drillmaster.context import Context

logger = logging.getLogger(__name__)

class Options(NamedTuple):
    network_name: str
    timeout: int
    run_new_containers: bool
    remove: bool

class AgentStatus:
    NULL = 'null'
    IN_PROGRESS = 'in-progress'
    STARTED = 'started'
    FAILED = 'failed'
    STOPPED = 'stopped'

class RunCondition:
    CREATED = 'created'
    STARTED = 'started'
    ALREADY_RUNNING = 'already-running'

class Actions:
    START = 'start'
    STOP = 'stop'

class ServiceAgentException(Exception):
    pass

class ServiceAgent(threading.Thread):

    def __init__(self, service, options: Options, context):
        # service: Service
        # context: RunningContext
        super().__init__()
        self.service = service
        self.options = options
        self.context = context
        self.open_dependencies = service.dependencies[:]
        self.open_dependants = service.dependants[:]
        self.status = AgentStatus.NULL
        self._action = None

    def __repr__(self):
        return "<ServiceAgent service={:s}>".format(self.service.name)

    @property
    def action(self):
        return self._action

    @action.setter
    def action(self, aktion):
        if not aktion in [Actions.START, Actions.STOP]:
            raise ServiceAgentException("Agent action must be one of start or stop")
        self._action = aktion

    @property
    def can_start(self):
        return self.open_dependencies == [] and self.status == AgentStatus.NULL

    @property
    def can_stop(self):
        return self.open_dependants == [] and self.status == AgentStatus.NULL

    @property
    def container_name_prefix(self):
        return "{:s}-drillmaster".format(self.service.name)

    def process_service_started(self, service):
        if service in self.open_dependencies:
            self.open_dependencies.remove(service)

    def process_service_stopped(self, service):
        if service in self.open_dependants:
            self.open_dependants.remove(service)

    def run_image(self): # returns RunCondition
        client = DockerClient.get_client()
        # If there are any running with the name prefix, connected to the same
        # network, skip creating
        existings = client.existing_on_network(self.container_name_prefix, self.options.network_name)
        if existings:
            # TODO fix this; it should be able to deal with multiple existing
            # containers
            existing = existings[0]
            if existing.status == 'running':
                logger.info("Running container for %s, not starting a new one", self.service.name)
                return RunCondition.ALREADY_RUNNING
            elif existing.status == 'exited':
                if not (self.options.run_new_containers or self.service.always_start_new):
                    logger.info("There is an existing container for %s, not creating a new one", self.service.name)
                    client.run_container(existing.id)
                    return RunCondition.STARTED
        self.service.env = Context.extrapolate_values(self.service.env)
        client.run_service_on_network(self.container_name_prefix,
                                      self.service,
                                      self.options.network_name)
        return RunCondition.CREATED


    def ping(self):
        start = time.monotonic()
        while time.monotonic() - start < self.options.timeout:
            if self.service.ping():
                logger.info("Service %s pinged successfully", self.service.name)
                return True
            time.sleep(0.1)
        logger.error("Could not ping service with timeout of {}".format(self.options.timeout))
        return False

    def start_service(self):
        self.action = Actions.START
        self.start()

    def stop_service(self):
        self.action = Actions.STOP
        self.start()

    def run(self):
        if self.action is None:
            self.status = AgentStatus.FAILED
            self.context.service_failed(self.service)
            raise ServiceAgentException("Agent cannot be started without an action set")
        self.status = AgentStatus.IN_PROGRESS
        if self.action == Actions.START:
            self.start_container()
        elif self.action == Actions.STOP:
            self.stop_container()

    def start_container(self):
        try:
            run_condition = self.run_image()
            if run_condition != RunCondition.ALREADY_RUNNING:
                if not self.ping():
                    self.status = AgentStatus.FAILED
                    self.context.service_failed(self.service)
                    return
            if run_condition == RunCondition.CREATED:
                self.service.post_start_init()
        except:
            logger.exception("Error starting service")
            self.status = AgentStatus.FAILED
            self.context.service_failed(self.service)
        else:
            logger.info("Service %s started successfully", self.service.name)
            self.status = AgentStatus.STARTED
            self.context.service_started(self.service)

    def stop_container(self):
        client = DockerClient.get_client()
        existings = client.existing_on_network(self.container_name_prefix,
                                               self.options.network_name)
        if not existings:
            logging.info("No containers to stop for %s", self.service.name)
        for existing in existings:
            if existing.status == 'running':
                existing.stop(timeout=self.options.timeout)
                logging.info("Stopped container %s", existing.name)
            if self.options.remove:
                logging.info("Removed container %s", existing.name)
                existing.remove()
        # If there were no exceptions, just mark it as stopped
        self.status = AgentStatus.STOPPED
        self.context.service_stopped(self.service)
