import logging
import random
import time

import docker
import docker.errors

from drillmaster.context import Context

logger = logging.getLogger(__name__)

DIGITS = "0123456789"

_the_docker = None

class DockerException(Exception):
    pass

class DockerClient:

    def __init__(self, lib_client):
        self.lib_client = lib_client

    @classmethod
    def get_client(cls):
        global _the_docker
        if _the_docker is None:
            _the_docker = cls(docker.from_env())
        return _the_docker

    def create_network(self, network_name):
        existing = self.lib_client.networks.list(names=[network_name])
        if existing:
            network = existing[0]
        else:
            network = self.lib_client.networks.create(network_name, driver="bridge")
            logger.info("Created network %s", network_name)
        return network

    def remove_network(self, network_name):
        networks = self.lib_client.networks.list(names=[network_name])
        if networks:
            networks[0].remove()
            logging.info("Removed network %s", network_name)


    def existing_on_network(self, name, network_name):
        return self.lib_client.containers.list(all=True, filters={'network': network_name,
                                                                  'name': name})

    def run_container(self, container_id):
        # The container should be already created but not in state running or starting
        self.lib_client.api.start(container_id)
        # Let's wait a little because the status of the container is
        # not set right away
        time.sleep(1)
        try:
            container = self.lib_client.containers.get(container_id)
        except docker.errors.NotFound:
            raise DockerException(
                "Something went terribly wrong: Could not find container {:s}".format(
                    container_id))
        if container.status != 'running':
            logs = self.lib_client.api.logs(container.id).decode('utf-8')
            raise DockerException(logs)
        return container


    def run_service_on_network(self, name_prefix, service, network_name): # service: services.Service
        container_name = "{:s}-{:s}".format(name_prefix, ''.join(random.sample(DIGITS, 4)))
        networking_config = self.lib_client.api.create_networking_config({
            network_name: self.lib_client.api.create_endpoint_config(aliases=[service.name])
        })
        host_config=self.lib_client.api.create_host_config(port_bindings=service.ports)
        try:
            container = self.lib_client.api.create_container(
                service.image,
                detach=True,
                name=container_name,
                ports=list(service.ports.keys()),
                environment=service.env,
                host_config=host_config,
                networking_config=networking_config,
                stop_signal=service.stop_signal)
        except docker.errors.ImageNotFound:
            raise DockerException("Image {:s} could not be found; please make sure it exists".format(service.image)) from None
        container = self.run_container(container.get('Id'))
        logger.info("Started container id %s for service %s", container.id, service.name)
