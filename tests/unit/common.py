import uuid
import time
from types import SimpleNamespace as Bunch

from miniboss.types import Options, Network

DEFAULT_OPTIONS = Options(network=Network(name='the-network', id='the-network-id'),
                          timeout=1,
                          remove=False,
                          run_dir='/etc',
                          build=[])


class FakeRunningContext:
    def __init__(self):
        self.started_services = []
        self.stopped_services = []
        self.failed_services = []

    def service_started(self, service):
        self.started_services.append(service)

    def service_stopped(self, service):
        self.stopped_services.append(service)

    def service_failed(self, failed_service):
        self.failed_services.append(failed_service)

class FakeService:
    image = 'not/used'
    dependants = []
    ports = {}
    env = {}
    always_start_new = False
    build_from_directory = None
    dockerfile = 'Dockerfile'

    def __init__(self, name='service1', dependencies=None, fail_ping=False, exception_at_init=None):
        self.name = name
        self.dependencies = dependencies or []
        self.fail_ping = fail_ping
        self.exception_at_init = exception_at_init
        self.ping_count = 0
        self.init_called = False
        self.pre_start_called = False

    def ping(self):
        self.ping_count += 1
        return not self.fail_ping

    def pre_start(self):
        self.pre_start_called = True

    def post_start(self):
        self.init_called = True
        if self.exception_at_init:
            raise self.exception_at_init()
        return True

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.name == other.name


class FakeContainer(Bunch):

    def __init__(self, **kwargs):
        self.stopped = False
        self.removed_at = None
        self.timeout = None
        super().__init__(**kwargs)

    def stop(self, timeout):
        self.stopped = True
        self.removed_at = None
        self.timeout = timeout

    def remove(self):
        time.sleep(0.1)
        self.removed_at = time.time()


class FakeDocker:
    Instance = None

    @classmethod
    def get_client(cls):
        return cls.Instance

    def __init__(self, network_name_id_mapping=None):
        self._networks_created = []
        self._networks_removed = []
        self._services_started = []
        self._existing_queried = []
        self._containers_ran = []
        self._images_built = []
        self._existing_containers = []
        self.network_name_id_mapping = network_name_id_mapping or {}

    def create_network(self, network_name):
        self._networks_created.append(network_name)
        return Bunch(id=self.network_name_id_mapping[network_name])

    def remove_network(self, network_name):
        self._networks_removed.append(network_name)

    def existing_on_network(self, name, network):
        self._existing_queried.append((name, network))
        for container in self._existing_containers:
            if (container.name.startswith(name) and
                self.network_name_id_mapping[container.network] == network.id):
                return [container]
        return []

    def run_service_on_network(self, name_prefix, service, network):
        self._services_started.append((name_prefix, service, network))

    def run_container(self, container_id):
        self._containers_ran.append(container_id)

    def build_image(self, build_dir, dockerfile, image_tag):
        self._images_built.append((build_dir, dockerfile, image_tag))
