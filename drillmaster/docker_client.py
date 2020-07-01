import logging
import random

import docker

from drillmaster.context import Context

logger = logging.getLogger(__name__)

DIGITS = "0123456789"

_the_docker = None

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
            network = docker.networks.create(network_name, driver="bridge")
            logger.info("Created network %s", network_name)
        return network

    def remove_network(self, network_name):
        networks = docker.networks.list(names=[options.network_name])
        if networks:
            networks[0].remove()
            logging.info("Removed network %s", options.network_name)


    def existing_on_network(self, name, network_name):
        return self.lib_client.containers.list(all=True, filters={'network': network_name,
                                                                  'name': name})

    def run_service_on_network(self, name_prefix, service, network_name): # service: services.Service
        container_name = "{:s}-{:s}".format(name_prefix, ''.join(random.sample(DIGITS, 4)))
        networking_config = self.lib_client.api.create_networking_config({
            network_name: self.lib_client.api.create_endpoint_config(aliases=[service.name])
        })
        host_config=self.lib_client.api.create_host_config(port_bindings=service.ports)
        container = self.lib_client.api.create_container(
            service.image,
            detach=True,
            name=container_name,
            ports=list(service.ports.keys()),
            environment=service.env,
            host_config=host_config,
            networking_config=networking_config)
        running = self.lib_client.api.start(container.get('Id'))
        logger.info("Started container id %s for service %s", running.id, self.service.name)
