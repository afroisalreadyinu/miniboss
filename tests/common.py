import uuid
import time
from types import SimpleNamespace as Bunch


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

class MockDocker:
    def __init__(self):
        parent = self
        self._networks = []
        self._networking_configs = None
        self._networks_created = []
        self._containers_created = {}
        self._containers_started = []
        self._existing_containers = []
        self._list_containers_query_params = None

        class Networks:
            def list(self, names):
                return [x for x in parent._networks if x.name in names]
            def create(self, network_name, driver=None):
                parent._networks_created.append((network_name, driver))
        self.networks = Networks()

        class Containers:
            def list(self, *args, **kwargs):
                filters = kwargs.get('filters', {})
                if 'name' in filters:
                    return [x for x in parent._existing_containers
                            if filters['name'] in x.name]
                return parent._existing_containers
        self.containers= Containers()

        class API:

            def create_networking_config(self, networking_dict):
                parent._networking_configs = networking_dict

            def create_host_config(*args, **kwargs):
                pass

            def create_endpoint_config(self, aliases=None):
                pass

            def create_container(self, image, **kwargs):
                _id = str(uuid.uuid4())
                parent._containers_created[_id] = {'image': image, **kwargs}
                return {'Id': _id}

            def start(self, container_id):
                parent._containers_started.append(container_id)
        self.api = API()
