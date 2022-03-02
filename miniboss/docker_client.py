import logging
import random
import time

import docker
import docker.errors

from miniboss.exceptions import DockerException, ContainerStartException
from miniboss.types import Network

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
            network = self.lib_client.networks.create(network_name, driver="bridge")
            logger.info("Created network %s", network_name)
        return network

    def remove_network(self, network_name):
        networks = self.lib_client.networks.list(names=[network_name])
        if networks:
            networks[0].remove()
            logger.info("Removed network %s", network_name)


    def existing_on_network(self, name, network: Network):
        return self.lib_client.containers.list(all=True, filters={'network': network.id,
                                                                  'name': name})

    def build_image(self, build_dir, dockerfile, image_tag):
        try:
            self.lib_client.images.build(tag=image_tag, path=build_dir, dockerfile=dockerfile)
        except docker.errors.BuildError as build_error:
            msg = "Error building image: {}".format(build_error.msg)
            raise DockerException(msg) from None
        except docker.errors.APIError as api_error:
            msg = "Error building image: {}".format(api_error.explanation)
            raise DockerException(msg) from None

    def run_container(self, container_id):
        # The container should be already created but not in state running or starting
        try:
            self.lib_client.api.start(container_id)
        except docker.errors.APIError as api_error:
            # This might be e.g. due to cgroups errors
            raise DockerException("Error starting container {}: {}".format(
                container_id, api_error.explanation)) from None
        # Let's wait a little because the status of the container is
        # not set right away
        time.sleep(1)
        try:
            container = self.lib_client.containers.get(container_id)
        except docker.errors.NotFound:
            raise DockerException(
                "Something went terribly wrong: Could not find container {:s}".format(
                    container_id)) from None
        if container.status != 'running':
            logs = self.lib_client.api.logs(container.id).decode('utf-8')
            raise ContainerStartException(logs, container.name)
        return container

    def check_image(self, tag):
        try:
            self.lib_client.images.get(tag)
        except docker.errors.ImageNotFound:
            pass
        else:
            return
        logger.info("Image %s does not exist, will pull it", tag)
        try:
            self.lib_client.images.pull(tag)
        except docker.errors.APIError as api_error:
            raise DockerException("Could not pull image {} due to API error: {}".format(
                tag, api_error.explanation)) from None


    def run_service_on_network(self,
                               name_prefix,
                               service,  # service: services.Service
                               network: Network):
        container_name = "{:s}-{:s}".format(name_prefix, ''.join(random.sample(DIGITS, 4)))
        networking_config = self.lib_client.api.create_networking_config({
            network.name: self.lib_client.api.create_endpoint_config(aliases=[service.name]),
        })
        host_config=self.lib_client.api.create_host_config(port_bindings=service.ports,
                                                           binds=service.volumes)
        self.check_image(service.image)
        try:
            container = self.lib_client.api.create_container(
                service.image,
                detach=True,
                name=container_name,
                ports=list(service.ports.keys()),
                environment=service.env,
                host_config=host_config,
                networking_config=networking_config,
                volumes=service.volume_def_to_binds(),
                stop_signal=service.stop_signal)
        except docker.errors.ImageNotFound:
            msg = "Image {:s} could not be found; please make sure it exists".format(service.image)
            raise DockerException(msg) from None
        container = self.run_container(container.get('Id'))
        logger.info("Started container id %s for service %s", container.id, service.name)
        return container_name
