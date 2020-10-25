import os
import unittest
import tempfile
import uuid

import docker
import docker.errors
import requests
from requests.exceptions import ConnectionError
import pytest

import miniboss
from miniboss.docker_client import DockerClient
from miniboss import exceptions
from miniboss.types import Network

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
        self.image_cleanup = []

    def tearDown(self):
        lib_client = get_lib_client()
        for container_name in self.container_cleanup:
            container = lib_client.containers.get(container_name)
            try:
                container.kill()
            except docker.errors.APIError:
                pass
            container.remove(force=True)
        for network_name in self.network_cleanup:
            network = lib_client.networks.get(network_name)
            network.remove()
        for image_name in self.image_cleanup:
            network = lib_client.images.remove(image_name)

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
                                                       Network('miniboss-test-network', ""))
        self.container_cleanup.append(container_name)
        resp = requests.get('http://localhost:8085')
        assert resp.status_code == 200
        lib_client = get_lib_client()
        containers = lib_client.containers.list()
        assert container_name in [c.name for c in containers]
        network = lib_client.networks.get('miniboss-test-network')
        assert len(network.containers) == 1
        assert network.containers[0].name == container_name


    def test_run_service_volume_mount(self):
        client = DockerClient.get_client()
        client.create_network('miniboss-test-network')
        self.network_cleanup.append('miniboss-test-network')
        #----------------------------
        context = tempfile.mkdtemp()
        with open(os.path.join(context, 'Dockerfile'), 'w') as dockerfile:
            dockerfile.write("""FROM python:3.7
WORKDIR /app
RUN pip install flask
COPY app.py .
CMD ["python3", "app.py"]""")
        with open(os.path.join(context, 'app.py'), 'w') as app_file:
            app_file.write("""
from flask import Flask
app = Flask('the-app')

@app.route("/")
def index():
    with open("/mnt/volume1/key.txt", 'r') as key_file:
        retval = key_file.read()
    return retval

app.run(host='0.0.0.0', port=8080)
""")
        lib_client = get_lib_client()
        lib_client.images.build(path=context, tag="mounted-container")
        self.image_cleanup.append("mounted-container")
        #----------------------------
        mount_dir = tempfile.mkdtemp()
        key = str(uuid.uuid4())
        with open(os.path.join(mount_dir, 'key.txt'), 'w') as keyfile:
            keyfile.write(key)
        class TestService(miniboss.Service):
            name = 'test-service'
            image = 'mounted-container'
            ports = {8080: 8080}
            volumes = {mount_dir: {'bind': '/mnt/volume1', 'mode': 'ro'}}
        service = TestService()
        container_name = client.run_service_on_network('miniboss-test-service',
                                                       service,
                                                       Network('miniboss-test-network', ""))
        self.container_cleanup.append(container_name)
        resp = requests.get('http://localhost:8080')
        assert resp.status_code == 200
        assert resp.text == key


    def test_check_image_invalid_url(self):
        client = DockerClient.get_client()
        with pytest.raises(exceptions.DockerException):
            client.check_image('somerepothatdoesntexist.org/imagename:imagetag')

    def test_check_image_missing_tag(self):
        lib_client = get_lib_client()
        lib_client.images.pull('registry:2')
        hub_container = lib_client.containers.run('registry:2', detach=True, ports={5000:5000})
        self.container_cleanup.append(hub_container.name)
        client = DockerClient.get_client()
        with pytest.raises(exceptions.DockerException):
            client.check_image("localhost:5000/this-repo:not-exist")


    def test_check_image_download_from_repo(self):
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
        self.image_cleanup.append("localhost:5000/allis:good")
        images = lib_client.images.list(name="localhost:5000/allis")
        assert len(images) == 1


    def test_run_container(self):
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
                                                       Network('miniboss-test-network', ""))
        self.container_cleanup.append(container_name)
        resp = requests.get('http://localhost:8085')
        assert resp.status_code == 200
        lib_client = get_lib_client()
        container = lib_client.containers.get(container_name)
        container.stop()
        # Let's make sure it's not running
        with pytest.raises(Exception):
            resp = requests.get('http://localhost:8085')
        # and restart it
        client.run_container(container.id)
        resp = requests.get('http://localhost:8085')
        assert resp.status_code == 200


    def test_print_error_on_container_dead(self):
        lib_client = get_lib_client()
        context = tempfile.mkdtemp()
        with open(os.path.join(context, 'Dockerfile'), 'w') as dockerfile:
            dockerfile.write("""FROM bash
WORKDIR /
COPY fail.sh /
RUN chmod +x /fail.sh
CMD ["/fail.sh"]""")
        with open(os.path.join(context, 'fail.sh'), 'w') as index:
            index.write("echo 'Going down' && exit 1")
        lib_client.images.build(path=context, tag="crashing-container")
        self.image_cleanup.append('crashing-container')
        client = DockerClient.get_client()
        client.create_network('miniboss-test-network')
        self.network_cleanup.append('miniboss-test-network')
        class FailingService(miniboss.Service):
            name = 'failing-service'
            image = 'crashing-container'
        service = FailingService()
        with pytest.raises(exceptions.ContainerStartException) as exception_context:
            client.run_service_on_network('miniboss-failing-service',
                                          service,
                                          Network('miniboss-test-network', ""))
        exception = exception_context.value
        self.container_cleanup.append(exception.container_name)
        assert exception.logs == "Going down\n"


    def test_build_image(self):
        lib_client = get_lib_client()
        context = tempfile.mkdtemp()
        with open(os.path.join(context, 'Dockerfile'), 'w') as dockerfile:
            dockerfile.write("""FROM nginx
COPY index.html /usr/share/nginx/html""")
        with open(os.path.join(context, 'index.html'), 'w') as index:
            index.write("ALL GOOD")
        client = DockerClient.get_client()
        client.build_image(context, 'Dockerfile', 'temporary-tag')
        images = lib_client.images.list(name="temporary-tag")
        assert len(images) == 1
