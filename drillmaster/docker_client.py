import logging
import random
import time

import docker

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

    def run_service_on_network(self, name_prefix, service, network_name): # service: services.Service
        container_name = "{:s}-{:s}".format(name_prefix, ''.join(random.sample(DIGITS, 4)))
        networking_config = self.lib_client.api.create_networking_config({
            network_name: self.lib_client.api.create_endpoint_config(aliases=[service.name])
        })
        host_config=self.lib_client.api.create_host_config(port_bindings=service.ports)
        container_image = self.lib_client.api.create_container(
            service.image,
            detach=True,
            name=container_name,
            ports=list(service.ports.keys()),
            environment=service.env,
            host_config=host_config,
            networking_config=networking_config)
        running = self.lib_client.api.start(container_image.get('Id'))
        if running is None:
            # We need to wait a little because the status of the container is
            # not set right away
            time.sleep(1)
            containers = self.existing_on_network(container_name, network_name)
            if not containers:
                raise DockerException(
                    "Something went terribly wrong: Could not create container for {:s}".format(
                        container_name))
            container = containers[0]
            if container.status != 'running':
                logs = self.lib_client.api.logs(container.id).decode('utf-8')
                raise DockerException(logs)
            import pdb;pdb.set_trace()
        logger.info("Started container id %s for service %s", running.id, self.service.name)
