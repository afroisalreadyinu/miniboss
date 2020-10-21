import unittest

import docker
from requests.exceptions import ConnectionError
import pytest

from miniboss.docker_client import DockerClient

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

    def test_create_remove_network(self):
        client = DockerClient.get_client()
        client.create_network('miniboss-test-network')
        lib_client = get_lib_client()
        networks = lib_client.networks.list()
        assert 'miniboss-test-network' in [n.name for n in networks]
        client.remove_network('miniboss-test-network')
        networks = lib_client.networks.list()
        assert 'miniboss-test-network' not in [n.name for n in networks]
