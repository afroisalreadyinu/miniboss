import time
import logging
from collections import Counter, deque
from collections.abc import Mapping

from miniboss import types
from miniboss.docker_client import DockerClient
from miniboss.types import Options, Network
from miniboss.running_context import RunningContext
from miniboss.context import Context
from miniboss.exceptions import MinibossException, ServiceLoadError, ServiceDefinitionError

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

KEYCLOAK_PORT = 8090
OSTKREUZ_PORT = 8080
ALLOWED_STOP_SIGNALS = ["SIGINT", "SIGTERM", "SIGKILL", "SIGQUIT"]

class ServiceMeta(type):
    # pylint: disable=too-many-branches
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
        if "always_start_new" in attrdict and not isinstance(attrdict["always_start_new"], bool):
            raise ServiceDefinitionError(
                "Field 'always_start_new' of service class {:s} must be a boolean".format(name))
        if "build_from_directory" in attrdict:
            build_dir = attrdict["build_from_directory"]
            if not isinstance(build_dir, str) or build_dir == '':
                raise ServiceDefinitionError(
                    "Field 'build_from_directory' of service class {:s} must be a non-empty string"
                    .format(name))
        if "dockerfile" in attrdict:
            dockerfile = attrdict["dockerfile"]
            if not isinstance(dockerfile, str) or dockerfile == '':
                raise ServiceDefinitionError(
                    "Field 'dockerfile' of service class {:s} must be a non-empty string"
                    .format(name))
        if "stop_signal" in attrdict:
            signal_name = attrdict["stop_signal"]
            if signal_name not in ALLOWED_STOP_SIGNALS:
                raise ServiceDefinitionError(
                    "Stop signal not allowed: {:s}".format(signal_name))
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
        return super().__new__(cls, name, bases, attrdict)


class Service(metaclass=ServiceMeta):
    name = None
    image = ""
    dependencies = []
    ports = {}
    env = {}
    always_start_new = False
    stop_signal = "SIGTERM"
    build_from_directory = None
    dockerfile = "Dockerfile"
    volumes = {}

    # pylint: disable=no-self-use
    def ping(self):
        return True

    def pre_start(self):
        pass

    def post_start(self):
        pass

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.name == other.name

    def __repr__(self):
        return "<miniboss.Service name: {}>".format(self.name)

    def volume_def_to_binds(self):
        if isinstance(self.volumes, dict):
            return [x['bind'] for x in self.volumes.values()]
        return [x.split(':')[1] for x in self.volumes]

def connect_services(services):
    name_counter = Counter()
    for service in services:
        name_counter[service.name] += 1
    multiples = [name for name,count in name_counter.items() if count > 1]
    if multiples:
        raise ServiceLoadError("Repeated service names: {:s}".format(",".join(multiples)))
    all_by_name = {service.name: service for service in services}
    for service in services:
        dependencies = service.dependencies[:]
        for dependency in dependencies:
            if dependency not in all_by_name:
                raise ServiceLoadError(
                    "Dependency {:s} of service {:s} not among services".format(
                        service.name, dependency))
        service.dependencies = [all_by_name[dependency] for dependency in dependencies]
    for service in services:
        service.dependants = [x for x in services if service in x.dependencies]
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
                raise ServiceLoadError("{:s} is to be excluded, but {:s} depends on it".format(
                    excluded_deps[0], service.name))
        missing = [x for x in exclude if x not in self.all_by_name]
        if missing:
            raise ServiceLoadError("Service{} to be excluded, but not defined: {}".format(
                "s" if len(missing) > 1 else "", ",".join(missing)))
        for name in exclude:
            self.all_by_name.pop(name)


    def exclude_for_stop(self, exclude):
        self.excluded = exclude
        for service_name in exclude:
            service = self.all_by_name[service_name]
            deps_to_be_stopped = [dep.name for dep in service.dependencies
                                  if dep.name not in exclude]
            if deps_to_be_stopped:
                raise ServiceLoadError("{:s} is to be stopped, but {:s} depends on it".format(
                    deps_to_be_stopped[0], service.name))
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
            msg = "No such service: {:s}".format(service_name)
            raise ServiceDefinitionError(msg)
        service = self.all_by_name[service_name]
        if not service.build_from_directory:
            msg = "Service {:s} cannot be built: No build directory specified".format(service.name)
            raise ServiceDefinitionError(msg)

    def start_all(self, options: Options):
        docker = DockerClient.get_client()
        network = docker.create_network(options.network.name)
        options.network.id = network.id
        self.running_context = RunningContext(self.all_by_name, options)
        while not (self.running_context.done or self.running_context.failed_services):
            for agent in self.running_context.ready_to_start:
                agent.start_service()
            time.sleep(0.01)
        failed = []
        if self.running_context.failed_services:
            failed = [x.name for x in self.running_context.failed_services]
            logger.error("Failed to start following services: %s", ",".join(failed))
        return [x for x in self.all_by_name.keys() if x not in failed]


    def stop_all(self, options: Options):
        docker = DockerClient.get_client()
        self.running_context = RunningContext(self.all_by_name, options)
        while not (self.running_context.done or self.running_context.failed_services):
            for agent in self.running_context.ready_to_stop:
                agent.stop_service()
            time.sleep(0.01)
        if options.remove and not self.excluded:
            docker.remove_network(options.network.name)


    def update_for_base_service(self, service_name):
        if service_name not in self.all_by_name:
            raise ServiceLoadError("No such service: {:s}".format(service_name))
        queue = deque()
        queue.append(self.all_by_name[service_name])
        required = []
        while queue:
            service = queue.popleft()
            required.append(service)
            for dependant in service.dependants:
                if dependant not in queue and dependant not in required:
                    queue.append(dependant)
        self.all_by_name = {service.name: service for service in required}

def start_services(maindir, exclude, network_name, timeout):
    if types.group_name is None:
        raise MinibossException(
            "Group name is not set; set it with miniboss.group_name in the main script"
        )
    Context.load_from(maindir)
    collection = ServiceCollection()
    collection.load_definitions()
    collection.exclude_for_start(exclude)
    network_name = network_name or "miniboss-{}".format(types.group_name)
    options = Options(network=Network(name=network_name, id=''),
                      timeout=timeout,
                      remove=False,
                      run_dir=maindir,
                      build=[])
    service_names = collection.start_all(options)
    logger.info("Started services: %s", ", ".join(service_names))
    Context.save_to(maindir)


def stop_services(maindir, exclude, network_name, remove, timeout):
    if types.group_name is None:
        raise MinibossException(
            "Group name is not set; set it with miniboss.group_name in the main script"
        )
    logger.info("Stopping services (excluded: %s)", "none" if not exclude else ",".join(exclude))
    network_name = network_name or "miniboss-{}".format(types.group_name)
    options = Options(network=Network(name=network_name, id=''),
                      timeout=timeout,
                      remove=remove,
                      run_dir=maindir,
                      build=[])
    collection = ServiceCollection()
    collection.load_definitions()
    collection.exclude_for_stop(exclude)
    collection.stop_all(options)
    if remove:
        Context.remove_file(maindir)

# pylint: disable=too-many-arguments
def reload_service(maindir, service, network_name, remove, timeout):
    if types.group_name is None:
        raise MinibossException(
            "Group name is not set; set it with miniboss.group_name in the main script"
        )
    network_name = network_name or "miniboss-{}".format(types.group_name)
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
