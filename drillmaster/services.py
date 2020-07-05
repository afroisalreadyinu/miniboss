import time
import logging
from collections import Counter, Mapping
import threading
import copy
from itertools import chain

import click
import requests
import furl
import requests.exceptions

from drillmaster.docker_client import DockerClient
from drillmaster.service_agent import (ServiceAgent,
                                       Options,
                                       StopOptions,
                                       AgentStatus)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

KEYCLOAK_PORT = 8090
OSTKREUZ_PORT = 8080


class ServiceLoadError(Exception):
    pass

class ServiceDefinitionError(Exception):
    pass

class ServiceMeta(type):
    def __new__(cls, name, bases, attrdict):
        if not bases:
            return super().__new__(cls, name, bases, attrdict)
        if not isinstance(attrdict.get("name"), str) or attrdict["name"] == "":
            raise ServiceDefinitionError(
                "Field 'name' of service class {:s} must be a non-empty string".format(name))
        if not isinstance(attrdict.get("image"), str) or attrdict["image"] == "":
            raise ServiceDefinitionError(
                "Field 'image' of service class {:s} must be a non-empty string".format(name))
        if "ports" in attrdict and not isinstance(attrdict["ports"], Mapping):
            raise ServiceDefinitionError(
                "Field 'ports' of service class {:s} must be a mapping".format(name))
        if "env" in attrdict and not isinstance(attrdict["env"], Mapping):
            raise ServiceDefinitionError(
                "Field 'env' of service class {:s} must be a mapping".format(name))
        return super().__new__(cls, name, bases, attrdict)


class Service(metaclass=ServiceMeta):
    name = None
    dependencies = []
    ports = {}
    env = {}
    always_start_new = False

    def ping(self):
        return True

    def post_start_init(self):
        pass

class RunningContext:

    def __init__(self, services_by_name, collection, options: Options):
        self.service_agents = {name: ServiceAgent(service, collection, options)
                               for name, service in services_by_name.items()}
        self.without_dependencies = [x for x in self.service_agents.values() if x.can_start]
        self.waiting_agents = {name: agent for name, agent in self.service_agents.items()
                               if not agent.can_start}

    @property
    def done(self):
        return all(x.status == AgentStatus.STARTED for x in self.service_agents.values())

    def service_started(self, started_service):
        self.service_agents.pop(started_service)
        startable = []
        for name, agent in self.waiting_agents.items():
            agent.process_service_started(started_service)
            if agent.can_start:
                startable.append(name)
        return [self.waiting_agents.pop(name) for name in startable]



class ServiceCollection:

    def __init__(self):
        self.all_by_name = {}
        self._base_class = Service
        self.running_context = None
        self.service_pop_lock = threading.Lock()
        self._failed = []

    def load_definitions(self):
        services = self._base_class.__subclasses__()
        if len(services) == 0:
            raise ServiceLoadError("No services defined")
        name_counter = Counter()
        for service in services:
            self.all_by_name[service.name] = service()
            name_counter[service.name] += 1
        multiples = [name for name,count in name_counter.items() if count > 1]
        if multiples:
            raise ServiceLoadError("Repeated service names: {:s}".format(",".join(multiples)))
        for service in self.all_by_name.values():
            dependencies = service.dependencies[:]
            for dependency in dependencies:
                if dependency not in self.all_by_name:
                    raise ServiceLoadError(
                        "Dependency {:s} of service {:s} not among services".format(
                            service.name, dependency))
            service.dependencies = [self.all_by_name[dependency] for dependency in dependencies]
        self.check_circular_dependencies()

    def exclude_for_start(self, exclude):
        for service in self.all_by_name.values():
            excluded_deps = [dep.name for dep in service.dependencies if dep.name in exclude]
            if excluded_deps:
                raise ServiceLoadError("{:s} is to be excluded, but {:s} depends on it".format(
                    excluded_deps[0], service.name))
        for name in exclude:
            self.all_by_name.pop(name)


    def exclude_for_stop(self, exclude):
        for service_name in exclude:
            service = self.all_by_name[service_name]
            deps_to_be_stopped = [dep.name for dep in service.dependencies if dep.name not in exclude]
            if deps_to_be_stopped:
                raise ServiceLoadError("{:s} is to be stopped, but {:s} depends on it".format(
                    deps_to_be_stopped[0], service.name))
            self.all_by_name.pop(service_name)


    def check_circular_dependencies(self):
        with_dependencies = [x for x in self.all_by_name.values() if x.dependencies != []]
        for service in with_dependencies:
            start = service.name
            count = 0
            def go_up_dependencies(checked):
                nonlocal count
                count += 1
                for dependency in checked.dependencies:
                    if dependency.name == start:
                        raise ServiceLoadError("Circular dependency detected")
                    if count == len(self.all_by_name):
                        return
                    go_up_dependencies(dependency)
            go_up_dependencies(service)

    def __len__(self):
        return len(self.all_by_name)

    @property
    def failed(self):
        return self._failed != []

    def start_next(self, started_service):
        with self.service_pop_lock:
            new_startables = self.running_context.service_started(started_service)
            for agent in new_startables:
                agent.start()

    def service_failed(self, failed_service):
        self._failed.append(failed_service)

    def start_all(self, options: Options):
        self.running_context = RunningContext(self.all_by_name, self, options)
        for agent in self.running_context.without_dependencies:
            agent.start()
        while not (self.running_context.done or self.failed):
            time.sleep(0.05)
        if self.failed:
            logger.error("Failed to start following services: %s", ",".join(self._failed))
        return list(x for x in self.all_by_name.keys() if x not in self._failed)

    def stop_all(self, options: StopOptions):
        docker = DockerClient.get_client()
        to_be_stopped = list(self.all_by_name.keys())
        while to_be_stopped:
            all_dependencies = []
            for service in to_be_stopped:
                all_dependencies.extend(d.name for d in self.all_by_name[service].dependencies)
                dependencies = set(all_dependencies)
            # pick a service that's not a dependency
            name = [x for x in to_be_stopped if x not in dependencies][0]
            prefix = "{}-drillmaster".format(name)
            existings = docker.existing_on_network(prefix, options.network_name)
            # existings = docker.containers.list(all=True, filters={'network': options.network_name,
            #                                                       'name': prefix})
            for existing in existings:
                if existing.status == 'running':
                    existing.stop(timeout=options.timeout)
                    logging.info("Stopped container %s", existing.name)
                if options.remove:
                    logging.info("Removed container %s", existing.name)
                    existing.remove()
            to_be_stopped.remove(name)
        if options.remove:
            docker.remove_network(options.network_name)


def start_services(run_new_containers, exclude, network_name, timeout):
    docker = DockerClient.get_client()
    collection = ServiceCollection()
    collection.load_definitions()
    collection.exclude_for_start(exclude)
    docker.create_network(network_name)
    service_names = collection.start_all(Options(run_new_containers, network_name, timeout))
    logger.info("Started services: %s", ", ".join(service_names))


def stop_services(exclude, network_name, remove, timeout):
    logger.info("Stopping services (excluded: %s)", "none" if not exclude else ",".join(exclude))
    options = StopOptions(network_name, remove, timeout)
    collection = ServiceCollection()
    collection.load_definitions()
    collection.exclude_for_stop(exclude)
    collection.stop_all(options)
