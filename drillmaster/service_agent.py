import threading
import random
import time
import logging
from typing import NamedTuple

from drillmaster.docker_client import get_client

logger = logging.getLogger(__name__)

DIGITS = "0123456789"

class Options(NamedTuple):
    create_new: bool
    network_name: str
    timeout: int

class ServiceAgent(threading.Thread):

    def __init__(self, service, collection, options: Options):
        # service: Service
        # collection: ServiceCollection
        super().__init__()
        self.service = service
        self.collection = collection
        self.options = options
        self.open_dependencies = [x.name for x in service.dependencies]

    @property
    def can_start(self):
        return self.open_dependencies == []

    def process_service_started(self, service_name):
        if service_name in self.open_dependencies:
            self.open_dependencies.remove(service_name)


    def run_image(self):
        client = get_client()
        # If there are any running with the name prefix, connected to the same
        # network, skip creating
        container_name_prefix = "{:s}-drillmaster".format(self.service.name)
        existings = client.containers.list(all=True,
                                          filters={'status': 'running',
                                                   'name': container_name_prefix,
                                                   'network': 'link-testing'})
        if existings:
            existing = existings[0]
            if existing.status == 'running':
                logger.info("There is an existing container for %s, not starting a new one", self.service.name)
                return
        container_name = "{:s}-{:s}".format(container_name_prefix, ''.join(random.sample(DIGITS, 4)))
        networking_config = client.api.create_networking_config({
            self.options.network_name: client.api.create_endpoint_config(aliases=[self.service.name])
        })
        host_config=client.api.create_host_config(port_bindings=self.service.ports)
        container = client.api.create_container(
            self.service.image,
            detach=True,
            name=container_name,
            ports=list(self.service.ports.keys()),
            environment=self.service.env,
            host_config=host_config,
            networking_config=networking_config)
        client.api.start(container.get('Id'))
        return container


    def ping(self):
        start = time.monotonic()
        while time.monotonic() - start < self.options.timeout:
            if self.service.ping():
                return True
            time.sleep(0.1)
        logger.error("Could not ping service with timeout of {}".format(self.options.timeout))
        return False

    def run(self):
        try:
            self.run_image()
            if not self.ping():
                self.collection.service_failed(self.service.name)
                return
            self.service.post_start_init()
            self.collection.start_next(self.service.name)
        except:
            logger.exception("Error starting service")
            self.collection.service_failed(self.service.name)
