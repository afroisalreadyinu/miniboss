import os
import threading
import time
from datetime import datetime
import logging

from miniboss import types
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


def differing_keys(specified, existing):
    """Diff the two environment dictionaries, the first one being the one specified
    in the service def, and the other of an existing container image. Only a one
    way diff; we ignore keys in `existing` that are not in `specified`. We are
    also converting the keys from specified to string because the values from
    existing are always strings anyway. """
    return [key for key,value in specified.items() if str(value) != existing.get(key)]


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
        self.run_condition = RunCondition()
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
        return "{:s}-{:s}".format(self.service.name, types.group_name)

    def process_service_started(self, service):
        if service in self.open_dependencies:
            self.open_dependencies.remove(service)

    def process_service_stopped(self, service):
        if service in self.open_dependants:
            self.open_dependants.remove(service)

    def build_image(self):
        client = DockerClient.get_client()
        time_tag = datetime.now().strftime("%Y-%m-%d-%H%M")
        image_tag = "{:s}-{:s}".format(self.service.name, time_tag)
        build_dir = os.path.join(self.options.run_dir, self.service.build_from)
        logger.info("Building image with tag %s for service %s from directory %s",
                    image_tag, self.service.name, build_dir)
        client.build_image(build_dir, self.service.dockerfile, image_tag)
        self.run_condition.build_image()
        return image_tag

    def _start_existing(self, existings):
        # pylint: disable=fixme
        # TODO fix this; it should be able to deal with multiple existing
        # containers
        existing = existings[0]
        if existing.status == 'running':
            logger.info("Found running container for %s, not starting a new one",
                        self.service.name)
            self.run_condition.already_running()
            return
        client = DockerClient.get_client()
        if existing.status == 'exited':
            existing_env = container_env(existing)
            diff_keys = differing_keys(self.service.env, existing_env)
            if diff_keys:
                logger.info("Differing env key(s) in existing container for service %s: %s",
                            self.service.name, ",".join(diff_keys))
            start_new = (self.service.always_start_new or
                         self.service.image not in existing.image.tags or
                         bool(diff_keys))
            if not start_new:
                logger.info("There is an existing container for %s, not creating a new one",
                            self.service.name)
                self.run_condition.started()
                client.run_container(existing.id)
                if not self.ping():
                    self._fail()


    def run_image(self): # returns RunCondition
        # pylint: disable=import-outside-toplevel, cyclic-import
        from miniboss.services import Service
        client = DockerClient.get_client()
        self.service.env = Context.extrapolate_values(self.service.env)
        # If there are any running with the name prefix, connected to the same
        # network, skip creating
        existings = client.existing_on_network(self.container_name_prefix,
                                               self.options.network)
        if existings:
            self._start_existing(existings)
            if self.run_condition.state in [RunCondition.STARTED, RunCondition.RUNNING]:
                return
        logger.info("Creating new container for service %s", self.service.name)
        self.service.pre_start()
        if self.service.pre_start.__func__ is not Service.pre_start:
            logger.info("pre_start for service %s ran", self.service.name)
        self.run_condition.pre_started()
        client.run_service_on_network(self.container_name_prefix,
                                      self.service,
                                      self.options.network)

        self.run_condition.started()
        if not self.ping():
            self._fail()
            return
        self.service.post_start()
        self.run_condition.post_started()
        if self.service.post_start.__func__ is not Service.post_start:
            logger.info("post_start for service %s ran", self.service.name)

    def ping(self):
        start = time.monotonic()
        while time.monotonic() - start < self.options.timeout:
            if self.service.ping():
                logger.info("Service %s pinged successfully", self.service.name)
                self.run_condition.pinged()
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

    def _fail(self):
        self.status = AgentStatus.FAILED
        self.run_condition.fail()
        self.context.service_failed(self.service)
        if RunCondition.START in self.run_condition.actions:
            self._stop_container(remove=True)

    def start_container(self):
        if (self.service.name in self.options.build
            or (self.service.build_from and self.service.image.endswith(':latest'))):
            tag = self.build_image()
            self.service.image = tag
        try:
            self.run_image()
        except Exception: # pylint: disable=broad-except
            logger.exception("Error starting service")
            self._fail()
        if self.run_condition.state == RunCondition.RUNNING:
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
