import os
import threading
import time
from datetime import datetime
import logging
from typing import NamedTuple

from miniboss.docker_client import DockerClient
from miniboss.context import Context

logger = logging.getLogger(__name__)

class Options(NamedTuple):
    network_name: str
    timeout: int
    run_new_containers: bool
    remove: bool
    run_dir: str

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

def container_env(container):
    env = container.attrs['Config']['Env']
    retval = {}
    for env_line in env:
        key, value = env_line.split('=', 1)
        retval[key] = value
    return retval

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
        return "{:s}-miniboss".format(self.service.name)

    def process_service_started(self, service):
        if service in self.open_dependencies:
            self.open_dependencies.remove(service)

    def process_service_stopped(self, service):
        if service in self.open_dependants:
            self.open_dependants.remove(service)

    def build_image(self):
        client = DockerClient.get_client()
        time_tag = datetime.now().strftime("%Y-%m-%d-%H%M")
        image_tag = "{:s}-miniboss-{:s}".format(self.service.name, time_tag)
        build_dir = os.path.join(self.options.run_dir, self.service.build_from_directory)
        logger.info("Building image with tag %s for service %s from directory %s",
                    image_tag, self.service.name, build_dir)
        client.build_image(build_dir, self.service.dockerfile, image_tag)
        return image_tag


    def run_image(self): # returns RunCondition
        client = DockerClient.get_client()
        self.service.env = Context.extrapolate_values(self.service.env)
        # If there are any running with the name prefix, connected to the same
        # network, skip creating
        existings = client.existing_on_network(self.container_name_prefix, self.options.network_name)
        if existings:
            # TODO fix this; it should be able to deal with multiple existing
            # containers
            existing = existings[0]
            if existing.status == 'running':
                logger.info("Found running container for %s, not starting a new one",
                            self.service.name)
                return RunCondition.ALREADY_RUNNING
            elif existing.status == 'exited':
                existing_env = container_env(existing)
                differing_keys = [key for key in self.service.env
                                  if existing_env.get(key) != self.service.env[key]]
                if differing_keys:
                    logger.info("Differing env key(s) in existing container for service %s: %s",
                                self.service.name, ",".join(differing_keys))
                start_new = (self.options.run_new_containers or
                             self.service.always_start_new or
                             self.service.image not in existing.image.tags or
                             bool(differing_keys))
                if not start_new:
                    logger.info("There is an existing container for %s, not creating a new one", self.service.name)
                    client.run_container(existing.id)
                    return RunCondition.STARTED
        logger.info("Creating new container for service %s", self.service.name)
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
