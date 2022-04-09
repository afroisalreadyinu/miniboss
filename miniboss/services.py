from __future__ import annotations
import time
import logging
from collections import Counter, deque
from collections.abc import Mapping
from typing import Any, Union, Callable

from miniboss import types
from miniboss.docker_client import DockerClient
from miniboss.types import Options, Network
from miniboss.running_context import RunningContext
from miniboss.context import Context
from miniboss.exceptions import ServiceLoadError, ServiceDefinitionError

logger = logging.getLogger(__name__)

KEYCLOAK_PORT = 8090
OSTKREUZ_PORT = 8080
ALLOWED_STOP_SIGNALS = ["SIGINT", "SIGTERM", "SIGKILL", "SIGQUIT"]

class ServiceMeta(type):
    # pylint: disable=too-many-branches,too-many-statements
    def __new__(cls, name, bases, attrdict):
        if not bases:
            return super().__new__(cls, name, bases, attrdict)
        if not isinstance(attrdict.get("name"), str) or attrdict["name"] == "":
            raise ServiceDefinitionError(
                f"Field 'name' of service class {name:s} must be a non-empty string")
        if not isinstance(attrdict.get("image"), str) or attrdict["image"] == "":
            raise ServiceDefinitionError(
                f"Field 'image' of service class {name:s} must be a non-empty string")
        if "ports" in attrdict and not isinstance(attrdict["ports"], Mapping):
            raise ServiceDefinitionError(
                f"Field 'ports' of service class {name:s} must be a mapping")
        if "env" in attrdict and not isinstance(attrdict["env"], Mapping):
            raise ServiceDefinitionError(
                f"Field 'env' of service class {name:s} must be a mapping")
        if "always_start_new" in attrdict and not isinstance(attrdict["always_start_new"], bool):
            raise ServiceDefinitionError(
                f"Field 'always_start_new' of service class {name:s} must be a boolean")
        if "build_from" in attrdict:
            build_dir = attrdict["build_from"]
            if not isinstance(build_dir, str) or build_dir == '':
                raise ServiceDefinitionError(
                    f"Field 'build_from' of service class {name:s} must be a non-empty string")
        if "dockerfile" in attrdict:
            dockerfile = attrdict["dockerfile"]
            if not isinstance(dockerfile, str) or dockerfile == '':
                raise ServiceDefinitionError(
                    f"Field 'dockerfile' of service class {name:s} must be a non-empty string")
        if "stop_signal" in attrdict:
            signal_name = attrdict["stop_signal"]
            if signal_name not in ALLOWED_STOP_SIGNALS:
                raise ServiceDefinitionError(f"Stop signal not allowed: {signal_name:s}")
        if "entrypoint" in attrdict:
            entrypoint = attrdict['entrypoint']
            if isinstance(entrypoint, list):
                if not all(isinstance(x, str) for x in entrypoint):
                    msg = (f"Field 'entrypoint' of service class {name:s} must " \
                           "be a string or list of strings")
                    raise ServiceDefinitionError(msg)
            elif not isinstance(entrypoint, str):
                raise ServiceDefinitionError(
                    f"Field 'entrypoint' of service class {name:s} must " \
                    "be a string or list of strings")
        if "cmd" in attrdict:
            cmd = attrdict['cmd']
            if isinstance(cmd, list):
                if not all(isinstance(x, str) for x in cmd):
                    raise ServiceDefinitionError(
                        f"Field 'cmd' of service class {name:s} must " \
                        "be a string or list of strings")
            elif not isinstance(cmd, str):
                raise ServiceDefinitionError(
                    f"Field 'cmd' of service class {name:s} must " \
                    "be a string or list of strings")
        if "user" in attrdict:
            user = attrdict['user']
            if not isinstance(user, str):
                raise ServiceDefinitionError(
                    f"Field 'user' of service class {name:s} must be a string")
        if "volumes" in attrdict:
            volumes = attrdict["volumes"]
            if isinstance(volumes, list):
                if not all(isinstance(x, str) for x in volumes):
                    raise ServiceDefinitionError(
                        "Volumes have to be defined either as a list of strings or a dict")
            elif isinstance(volumes, dict):
                if not all(isinstance(x, str) for x in volumes.keys()):
                    raise ServiceDefinitionError("Volume definition keys have to be strings")
                for volume in volumes.values():
                    if not isinstance(volume, dict):
                        raise ServiceDefinitionError("Volume definition values have to be dicts")
                    if not isinstance(volume.get('bind'), str):
                        raise ServiceDefinitionError(
                            "Volume definitions have to specify 'bind' key")
            else:
                raise ServiceDefinitionError(
                    "Volumes have to be defined either as a list of strings or a dict")
        return super().__new__(cls, name, bases, attrdict)


class Service(metaclass=ServiceMeta):
    name: str = ""
    image: str = ""
    dependencies: list[Service] = []
    _dependants: list[Service] = []
    ports: dict[int, int] = {}
    env: dict[str, Any] = {}
    always_start_new = False
    stop_signal = "SIGTERM"
    build_from = None
    dockerfile = "Dockerfile"
    entrypoint: str = ""
    cmd: str = ""
    user: str = ""
    volumes: Union[list[str], dict[str, dict[str, str]]] = {}

    # pylint: disable=no-self-use
    def ping(self) -> bool:
        return True

    def pre_start(self) -> None:
        pass

    def post_start(self) -> None:
        pass

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other) -> bool:
        return self.__class__ == other.__class__ and self.name == other.name

    def __repr__(self) -> str:
        return f"<miniboss.Service name: {self.name}>"

    def volume_def_to_binds(self) -> list[str]:
        if isinstance(self.volumes, dict):
            return [x['bind'] for x in self.volumes.values()]
        return [x.split(':')[1] for x in self.volumes]

def connect_services(services: list[Service]) -> dict[str, Service]:
    name_counter: Counter[str] = Counter()
    for service in services:
        name_counter[service.name] += 1
    multiples = [name for name,count in name_counter.items() if count > 1]
    if multiples:
        raise ServiceLoadError(f'Repeated service names: {",".join(multiples)}')
    all_by_name = {service.name: service for service in services}
    for service in services:
        if isinstance(service, str):
            service = all_by_name[service]
        actual_deps = []
        for dependency in service.dependencies:
            if isinstance(dependency, str):
                if dependency not in all_by_name:
                    raise ServiceLoadError(
                        f"Dependency {service.name:s} of service {dependency:s} not among services")
                dependency = all_by_name[dependency]
            actual_deps.append(dependency)
        service.dependencies = actual_deps
    for service in services:
        service._dependants = [x for x in services if service in x.dependencies]
    return all_by_name

class ServiceCollection:

    def __init__(self):
        self.all_by_name = {}
        self._base_class = Service
        self.running_context = None
        self.excluded = []

    def load_definitions(self):
        services = self._base_class.__subclasses__()
        if len(services) == 0:
            raise ServiceLoadError("No services defined")
        self.all_by_name = connect_services(list(service() for service in services))
        self.check_circular_dependencies()

    def exclude_for_start(self, exclude):
        self.excluded = exclude
        for service in self.all_by_name.values():
            if service.name in exclude:
                continue
            excluded_deps = [dep.name for dep in service.dependencies if dep.name in exclude]
            if excluded_deps:
                msg = f"{excluded_deps[0]} is to be excluded, but {service.name:s} depends on it"
                raise ServiceLoadError(msg)
        missing = [x for x in exclude if x not in self.all_by_name]
        if missing:
            multiple = "s" if len(missing) > 1 else ""
            msg = f"Service{multiple} to be excluded, but not defined: {','.join(missing)}"
            raise ServiceLoadError(msg)
        for name in exclude:
            self.all_by_name.pop(name)


    def exclude_for_stop(self, exclude):
        self.excluded = exclude
        for service_name in exclude:
            service = self.all_by_name[service_name]
            deps_to_be_stopped = [dep.name for dep in service.dependencies
                                  if dep.name not in exclude]
            if deps_to_be_stopped:
                msg = f"{deps_to_be_stopped[0]} is to be stopped, but {service.name} depends on it"
                raise ServiceLoadError(msg)
            self.all_by_name.pop(service_name)


    def check_circular_dependencies(self):
        with_dependencies = [x for x in self.all_by_name.values() if x.dependencies != []]
        # pylint: disable=cell-var-from-loop
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

    def check_can_be_built(self, service_name):
        if not service_name in self.all_by_name:
            raise ServiceDefinitionError(f"No such service: {service_name}")
        service = self.all_by_name[service_name]
        if not service.build_from:
            msg = f"Service {service.name} cannot be built: No build directory specified"
            raise ServiceDefinitionError(msg)

    def start_all(self, options: Options) -> list[str]:
        docker = DockerClient.get_client()
        network = docker.create_network(options.network.name)
        options.network.id = network.id
        self.running_context = RunningContext(self.all_by_name, options)
        while not self.running_context.done:
            for agent in self.running_context.ready_to_start:
                agent.start_service()
            time.sleep(0.01)
        failed = []
        if self.running_context.failed_services:
            failed = [x.name for x in self.running_context.failed_services]
            logger.error("Failed to start following services: %s", ",".join(failed))
        return [x for x in self.all_by_name.keys() if x not in failed]


    def stop_all(self, options: Options) -> list[str]:
        docker = DockerClient.get_client()
        self.running_context = RunningContext(self.all_by_name, options)
        stopped = []
        while not (self.running_context.done or self.running_context.failed_services):
            for agent in self.running_context.ready_to_stop:
                agent.stop_service()
                stopped.append(agent.service.name)
            time.sleep(0.01)
        if options.remove and not self.excluded:
            docker.remove_network(options.network.name)
        return stopped


    def update_for_base_service(self, service_name):
        if service_name not in self.all_by_name:
            raise ServiceLoadError(f"No such service: {service_name}")
        queue = deque()
        queue.append(self.all_by_name[service_name])
        required = []
        while queue:
            service = queue.popleft()
            required.append(service)
            for dependant in service._dependants:
                if dependant not in queue and dependant not in required:
                    queue.append(dependant)
        self.all_by_name = {service.name: service for service in required}

SingleServiceHookType = Callable[[str], Any]

ServicesHookType  = Callable[[list[str]], Any]

def noop(*_, **__):
    pass

_start_services_hook: ServicesHookType = noop

def on_start_services(hook_func: ServicesHookType):
    global _start_services_hook
    _start_services_hook = hook_func

def start_services(maindir: str, exclude: list[str], network_name: str, timeout: int):
    types.update_group_name(maindir)
    Context.load_from(maindir)
    collection = ServiceCollection()
    collection.load_definitions()
    collection.exclude_for_start(exclude)
    network_name = network_name or f"miniboss-{types.group_name}"
    options = Options(network=Network(name=network_name, id=''),
                      timeout=timeout,
                      remove=False,
                      run_dir=maindir,
                      build=[])
    service_names = collection.start_all(options)
    logger.info("Started services: %s", ", ".join(service_names))
    Context.save_to(maindir)
    try:
        _start_services_hook(service_names)
    except KeyboardInterrupt:
        logger.info("Interrupted on_start_services hook")
        return
    except: # pylint: disable=bare-except
        logger.exception("Error running on_start_services hook")


_stop_services_hook: ServicesHookType = noop

def on_stop_services(hook_func: ServicesHookType):
    global _stop_services_hook
    _stop_services_hook = hook_func

def stop_services(maindir: str, excluded: list[str], network_name: str, remove: bool, timeout: int):
    types.update_group_name(maindir)
    logger.info("Stopping services (excluded: %s)", "none" if not excluded else ",".join(excluded))
    network_name = network_name or f"miniboss-{types.group_name}"
    options = Options(network=Network(name=network_name, id=''),
                      timeout=timeout,
                      remove=remove,
                      run_dir=maindir,
                      build=[])
    collection = ServiceCollection()
    collection.load_definitions()
    collection.exclude_for_stop(excluded)
    stopped = collection.stop_all(options)
    if remove:
        Context.remove_file(maindir)
    try:
        _stop_services_hook(stopped)
    except KeyboardInterrupt:
        logger.info("Interrupted on_stop_services hook")
        return
    except: # pylint: disable=bare-except
        logger.exception("Error running on_stop_services hook")


_reload_service_hook: SingleServiceHookType = noop

def on_reload_service(hook_func: SingleServiceHookType):
    global _reload_service_hook
    _reload_service_hook = hook_func

# pylint: disable=too-many-arguments
def reload_service(maindir: str, service: str, network_name: str, remove: bool, timeout: int):
    types.update_group_name(maindir)
    network_name = network_name or f"miniboss-{types.group_name}"
    options = Options(network=Network(name=network_name, id=''),
                      timeout=timeout,
                      remove=remove,
                      run_dir=maindir,
                      build=[service])
    stop_collection = ServiceCollection()
    stop_collection.load_definitions()
    stop_collection.check_can_be_built(service)
    stop_collection.update_for_base_service(service)
    stop_collection.stop_all(options)
    # We don't need to do this earlier, as the context is not used by the stop
    # functionality
    Context.load_from(maindir)
    start_collection = ServiceCollection()
    start_collection.load_definitions()
    start_collection.start_all(options)
    Context.save_to(maindir)
    try:
        _reload_service_hook(service)
    except KeyboardInterrupt:
        logger.info("Interrupted on_stop_services hook")
        return
    except: # pylint: disable=bare-except
        logger.exception("Error running on_stop_services hook")
