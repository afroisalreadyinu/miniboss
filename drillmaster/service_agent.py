import threading
import random
import time
import logging

from drillmaster.docker_client import get_client

logger = logging.getLogger(__name__)

DIGITS = "0123456789"

class ServiceAgent(threading.Thread):

    def __init__(self, service, network_name, collection, timeout):
        # service: Service
        # collection: ServiceCollection
        super().__init__()
        self.service = service
        self.network_name = network_name
        self.collection = collection
        self.timeout = timeout
        self.open_dependencies = [x.name for x in service.dependencies]

    @property
    def can_start(self):
        return self.open_dependencies == []

    def process_service_started(self, service_name):
        if service_name in self.open_dependencies:
            self.open_dependencies.remove(service_name)


    def run_image(self):
        client = get_client()
        container_name = "{:s}-drillmaster-{:s}".format(self.service.name,
                                                        ''.join(random.sample(DIGITS, 4)))
        networking_config = client.api.create_networking_config({
            self.network_name: client.api.create_endpoint_config(aliases=[self.service.name])
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
        while time.monotonic() - start < self.timeout:
            if self.service.ping(self.timeout):
                return True
        logger.error("Could not ping service with timeout of {}".format(self.timeout))
        return False

    def run(self):
        try:
            self.run_image()
            if not self.ping():
                self.collection.service_failed(self.service.name)
                return
            self.collection.start_next(self.service.name)
        except:
            logger.exception("Error starting service")
            self.collection.service_failed(self.service.name)
