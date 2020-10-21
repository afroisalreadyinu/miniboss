import os
import unittest
import tempfile

import docker
import requests
from requests.exceptions import ConnectionError
import pytest

import miniboss
from miniboss.docker_client import DockerClient
from miniboss import exceptions

_lib_client = None

def get_lib_client():
    global _lib_client
    if _lib_client is None:
        _lib_client = docker.from_env()
    return _lib_client


def docker_unavailable():
    client = get_lib_client()
    try:
        client.ping()
    except ConnectionError:
        return True
    return False


@pytest.mark.skipif(docker_unavailable(), reason="docker service is not available")
class DockerClientTests(unittest.TestCase):

    def setUp(self):
        self.network_cleanup = []
        self.container_cleanup = []

    def tearDown(self):
        lib_client = get_lib_client()
        for container_name in self.container_cleanup:
            container = lib_client.containers.get(container_name)
            container.kill()
            container.remove(force=True)
        for network_name in self.network_cleanup:
            network = lib_client.networks.get(network_name)
            network.remove()

    def test_create_remove_network(self):
        client = DockerClient.get_client()
        client.create_network('miniboss-test-network')
        lib_client = get_lib_client()
        networks = lib_client.networks.list()
        assert 'miniboss-test-network' in [n.name for n in networks]
        client.remove_network('miniboss-test-network')
        networks = lib_client.networks.list()
        assert 'miniboss-test-network' not in [n.name for n in networks]


    def test_run_service_on_network(self):
        client = DockerClient.get_client()
        client.create_network('miniboss-test-network')
        self.network_cleanup.append('miniboss-test-network')
        class TestService(miniboss.Service):
            name = 'test-service'
            image = 'nginx'
            ports = {80: 8085}
        service = TestService()
        container_name = client.run_service_on_network('miniboss-test-service',
                                                       service,
                                                       'miniboss-test-network')
        self.container_cleanup.append(container_name)
        resp = requests.get('http://localhost:8085')
        assert resp.status_code == 200
        lib_client = get_lib_client()
        containers = lib_client.containers.list()
        assert container_name in [c.name for c in containers]


    def test_check_image_invalid_url(self):
        client = DockerClient.get_client()
        with pytest.raises(exceptions.DockerException):
            client.check_image('somerepothatdoesntexist.org/imagename:imagetag')


    def test_check_image(self):
        lib_client = get_lib_client()
        context = tempfile.mkdtemp()
        with open(os.path.join(context, 'Dockerfile'), 'w') as dockerfile:
            dockerfile.write("""FROM nginx
COPY index.html /usr/share/nginx/html""")
        with open(os.path.join(context, 'index.html'), 'w') as index:
            index.write("ALL GOOD")
        lib_client.images.build(path=context, tag="localhost:5000/allis:good")
        lib_client.images.pull('registry:2')
        hub_container = lib_client.containers.run('registry:2', detach=True, ports={5000:5000})
        self.container_cleanup.append(hub_container.name)
        lib_client.images.push("localhost:5000/allis:good")
        #Let's delete the image from the local cache so that it has to be downloaded
        lib_client.images.remove("localhost:5000/allis:good")
        client = DockerClient.get_client()
        images = lib_client.images.list(name="localhost:5000/allis")
        assert len(images) == 0
        client.check_image("localhost:5000/allis:good")
        images = lib_client.images.list(name="localhost:5000/allis")
        assert len(images) == 1


    def test_run_container(self):
        pass


    def test_build_image(self):
        pass
