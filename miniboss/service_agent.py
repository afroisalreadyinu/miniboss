import os
import threading
import time
from datetime import datetime
import logging

from miniboss.docker_client import DockerClient
from miniboss.context import Context
from miniboss.types import AgentStatus, RunCondition, Actions, Options
from miniboss.exceptions import ServiceAgentException

logger = logging.getLogger(__name__)

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
        existings = client.existing_on_network(self.container_name_prefix,
                                               self.options.network)
        if existings:
            # pylint: disable=fixme
            # TODO fix this; it should be able to deal with multiple existing
            # containers
            existing = existings[0]
            if existing.status == 'running':
                logger.info("Found running container for %s, not starting a new one",
                            self.service.name)
                return RunCondition.ALREADY_RUNNING
            if existing.status == 'exited':
                existing_env = container_env(existing)
                differing_keys = [key for key in self.service.env
                                  if existing_env.get(key) != self.service.env[key]]
                if differing_keys:
                    logger.info("Differing env key(s) in existing container for service %s: %s",
                                self.service.name, ",".join(differing_keys))
                start_new = (self.service.always_start_new or
                             self.service.image not in existing.image.tags or
                             bool(differing_keys))
                if not start_new:
                    logger.info("There is an existing container for %s, not creating a new one",
                                self.service.name)
                    client.run_container(existing.id)
                    return RunCondition.STARTED
        logger.info("Creating new container for service %s", self.service.name)
        client.run_service_on_network(self.container_name_prefix,
                                      self.service,
                                      self.options.network)
        return RunCondition.CREATED


    def ping(self):
        start = time.monotonic()
        while time.monotonic() - start < self.options.timeout:
            if self.service.ping():
                logger.info("Service %s pinged successfully", self.service.name)
                return True
            time.sleep(0.1)
        logger.error("Could not ping service with timeout of %d", self.options.timeout)
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

    def _fail(self, run_condition):
        self.status = AgentStatus.FAILED
        self.context.service_failed(self.service)
        if run_condition in [RunCondition.CREATED, RunCondition.CREATED]:
            self._stop_container(remove=True)

    def start_container(self):
        # pylint: disable=import-outside-toplevel, cyclic-import
        from miniboss.services import Service
        run_condition = RunCondition.NULL
        try:
            self.service.pre_start()
            if self.service.pre_start is not Service.pre_start:
                logger.info("pre_start for service %s ran", self.service.name)
            run_condition = self.run_image()
            if run_condition != RunCondition.ALREADY_RUNNING:
                if not self.ping():
                    self._fail(run_condition)
                    return
            if run_condition == RunCondition.CREATED:
                self.service.post_start()
                if self.service.post_start is not Service.post_start:
                    logger.info("post_start for service %s ran", self.service.name)
        except Exception: # pylint: disable=broad-except
            logger.exception("Error starting service")
            self._fail(run_condition)
        else:
            logger.info("Service %s started successfully", self.service.name)
            self.status = AgentStatus.STARTED
            self.context.service_started(self.service)

    def _stop_container(self, remove):
        client = DockerClient.get_client()
        existings = client.existing_on_network(self.container_name_prefix,
                                               self.options.network)
        if not existings:
            logging.info("No containers to stop for %s", self.service.name)
        for existing in existings:
            if existing.status == 'running':
                existing.stop(timeout=self.options.timeout)
                logging.info("Stopped container %s", existing.name)
            if remove:
                existing.remove()
                logging.info("Removed container %s", existing.name)

    def stop_container(self):
        self._stop_container(remove=self.options.remove)
        self.status = AgentStatus.STOPPED
        self.context.service_stopped(self.service)
