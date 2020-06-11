import unittest

import pytest

from drillmaster.services import Service, ServiceLoadError
from drillmaster import services

class ServiceLoadTests(unittest.TestCase):

    def test_raise_exception_on_same_name(self):
        services.Services = None
        class NewServiceBaseOne(Service):
            pass
        class ServiceOne(NewServiceBaseOne):
            name = "hello"
        class ServiceTwo(NewServiceBaseOne):
            name = "hello"
        with pytest.raises(ServiceLoadError):
            NewServiceBaseOne.load_definitions()


    def test_raise_exception_on_circular_dependency(self):
        services.Services = None
        class NewServiceBaseTwo(Service):
            pass
        class ServiceOne(NewServiceBaseTwo):
            name = "hello"
            dependencies = ["howareyou"]

        class ServiceTwo(NewServiceBaseTwo):
            name = "goodbye"
            dependencies = ["hello"]

        class ServiceThree(NewServiceBaseTwo):
            name = "howareyou"
            dependencies = ["goodbye"]

        with pytest.raises(ServiceLoadError):
            NewServiceBaseTwo.load_definitions()


    def test_load_services(self):
        services.Services = None
        class NewServiceBaseThree(Service):
            pass

        class ServiceOne(NewServiceBaseThree):
            name = "hello"
            dependencies = ["howareyou"]

        class ServiceTwo(NewServiceBaseThree):
            name = "goodbye"
            dependencies = ["hello"]

        class ServiceThree(NewServiceBaseThree):
            name = "howareyou"

        NewServiceBaseThree.load_definitions()
        assert len(services.Services) == 3

class MockDocker:
    def __init__(self):
        parent = self
        self._networks = []
        class Networks:
            def list(self, names):
                return [x for x in parent._networks if x in names]
            def create(self, network_name, driver=None):
                parent._networks.append((network_name, driver))
        self.networks = Networks()


class ServiceModifyTests(unittest.TestCase):

    def setUp(self):
        self.docker = MockDocker()
        class DockerInit:
            @classmethod
            def from_env(cls):
                return self.docker

        services.docker = DockerInit

    def test_start_service_create_network(self):
        services.Services = None

        class ServiceOne(Service):
            name = "hello"
            dependencies = []
        services.start_services(False, [], "drillmaster")
        assert self.docker._networks == [("drillmaster", "bridge")]
        del ServiceOne
