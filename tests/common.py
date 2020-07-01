import uuid
import time
from types import SimpleNamespace as Bunch

class FakeServiceCollection:
    def __init__(self):
        self.started_service = None
        self.failed_service = None

    def start_next(self, started_service):
        self.started_service = started_service

    def service_failed(self, failed_service):
        self.failed_service = failed_service

class FakeService:
    name = 'service1'
    image = 'not/used'
    dependencies = []
    ports = {}
    env = {}
    always_start_new = False

    def __init__(self, fail_ping=False, exception_at_init=None):
        self.fail_ping = fail_ping
        self.exception_at_init = exception_at_init
        self.ping_count = 0
        self.init_called = False

    def ping(self):
        self.ping_count += 1
        return not self.fail_ping

    def post_start_init(self):
        self.init_called = True
        if self.exception_at_init:
            raise self.exception_at_init()
        return True


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

    def __init__(self):
        self._networks_created = []
        self._services_started = []
        self._existing_queried = []

        self._existing_containers = []

    def create_network(self, network_name):
        self._networks_created.append(network_name)

    def remove_network(self, network_name):
        pass

    def existing_on_network(self, name, network_name):
        self._existing_queried.append((name, network_name))
        for container in self._existing_containers:
            if container.name.startswith(name) and container.network == network_name:
                return [container]
        return []

    def run_service_on_network(self, name_prefix, service, network_name):
        self._services_started.append((name_prefix, service, network_name))
