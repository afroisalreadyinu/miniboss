import unittest

import pytest

from drillmaster.services import (Service,
                                  ServiceCollection,
                                  ServiceLoadError,
                                  ServiceDefinitionError)
from drillmaster import services

class MockDocker:
    def __init__(self):
        parent = self
        self._networks = []
        self._networking_configs = None
        self._networks_created = []
        class Networks:
            def list(self, names):
                return [x for x in parent._networks if x in names]
            def create(self, network_name, driver=None):
                parent._networks_created.append((network_name, driver))
        self.networks = Networks()
        class API:
            def create_networking_config(self, networking_dict):
                parent._networking_configs = networking_dict
            def create_host_config(*args, **kwargs):
                pass
            def create_endpoint_config(self, aliases=None):
                pass
            def create_container(self, image, **kwargs):
                return {'Id': '1234'}
            def start(self, container_id):
                pass
        self.api = API()


class ServiceDefinitionTests(unittest.TestCase):

    def test_missing_name(self):
        with pytest.raises(ServiceDefinitionError):
            class NewService(Service):
                pass

        with pytest.raises(ServiceDefinitionError):
            class NewService(Service):
                name = "yes"


    def test_missing_image(self):
        with pytest.raises(ServiceDefinitionError):
            class NewService(Service):
                name = "yes"

        with pytest.raises(ServiceDefinitionError):
            class NewService(Service):
                name = "yes"
                image = 34.56


    def test_invalid_field_types(self):
        with pytest.raises(ServiceDefinitionError):
            class NewService(Service):
                name = "yes"
                image = "yes"
                ports = "no"

        with pytest.raises(ServiceDefinitionError):
            class NewService(Service):
                name = "yes"
                image = "yes"
                env = "no"


class ServiceCollectionTests(unittest.TestCase):

    def setUp(self):
        self.docker = services.the_docker = MockDocker()

    def test_raise_exception_on_same_name(self):
        collection = ServiceCollection()
        class NewServiceBaseOne(Service):
            name = "not used"
            image = "not used"

        collection._base_class = NewServiceBaseOne
        class ServiceOne(NewServiceBaseOne):
            name = "hello"
            image = "hello"
        class ServiceTwo(NewServiceBaseOne):
            name = "hello"
            image = "hello"
        with pytest.raises(ServiceLoadError):
            collection.load_definitions()


    def test_raise_exception_on_circular_dependency(self):
        collection = ServiceCollection()
        class NewServiceBaseTwo(Service):
            name = "not used"
            image = "not used"
        collection._base_class = NewServiceBaseTwo
        class ServiceOne(NewServiceBaseTwo):
            name = "hello"
            image = "hello"
            dependencies = ["howareyou"]

        class ServiceTwo(NewServiceBaseTwo):
            name = "goodbye"
            image = "hello"
            dependencies = ["hello"]

        class ServiceThree(NewServiceBaseTwo):
            name = "howareyou"
            image = "hello"
            dependencies = ["goodbye"]

        with pytest.raises(ServiceLoadError):
            collection.load_definitions()


    def test_load_services(self):
        collection = ServiceCollection()
        class NewServiceBaseThree(Service):
            name = "not used"
            image = "not used"
        collection._base_class = NewServiceBaseThree
        class ServiceOne(NewServiceBaseThree):
            name = "hello"
            image = "hello"
            dependencies = ["howareyou"]

        class ServiceTwo(NewServiceBaseThree):
            name = "goodbye"
            image = "hello"
            dependencies = ["hello"]

        class ServiceThree(NewServiceBaseThree):
            name = "howareyou"
            image = "hello"

        collection.load_definitions()
        assert len(collection) == 3

    #@patch('drillmaster.services.threading.Thread')
    def test_start_all(self):
        collection = ServiceCollection()
        class NewServiceBaseFour(Service):
            name = "not used"
            image = "not used"
        collection._base_class = NewServiceBaseFour
        class ServiceOne(NewServiceBaseFour):
            name = "hello"
            image = "hello"
            dependencies = ["howareyou"]

        class ServiceTwo(NewServiceBaseFour):
            name = "goodbye"
            image = "hello"
            dependencies = ["hello"]

        class ServiceThree(NewServiceBaseFour):
            name = "howareyou"
            image = "hello"
        collection.load_definitions()
        collection.start_all('the-network')



class ServiceCommandTests(unittest.TestCase):

    def setUp(self):
        self.docker = MockDocker()
        class DockerInit:
            @classmethod
            def from_env(cls):
                return self.docker

        services.docker = DockerInit
        class MockServiceCollection:
            def load_definitions(self):
                pass
            def start_all(self):
                return ["one", "two"]
        services.ServiceCollection = MockServiceCollection

    def test_start_service_create_network(self):
        services.start_services(False, [], "drillmaster")
        assert self.docker._networks == [("drillmaster", "bridge")]


    def test_start_service_skip_service_creation_if_exists(self):
        self.docker._networks = ["drillmaster"]
        services.start_services(False, [], "drillmaster")
        assert self.docker._networks_created == []
