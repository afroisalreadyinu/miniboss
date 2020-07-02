import unittest
from unittest.mock import patch
from types import SimpleNamespace as Bunch

import pytest

from drillmaster.services import (Service,
                                  ServiceLoadError,
                                  RunningContext,
                                  ServiceCollection,
                                  ServiceAgent,
                                  ServiceDefinitionError)
from drillmaster.service_agent import Options, StopOptions
from drillmaster import services, service_agent

from common import FakeDocker, FakeContainer

class RunningContextTests(unittest.TestCase):

    def test_service_started(self):
        collection = object()
        service1 = Bunch(name='service1', dependencies=[])
        service2 = Bunch(name='service2', dependencies=[service1])
        context = RunningContext({'service1': service1, 'service2': service2},
                                 collection, Options(False, 'the-network', 50))
        startable = context.service_started('service1')
        assert len(startable) == 1
        assert startable[0].service is service2


    def test_done(self):
        collection = object()
        service1 = Bunch(name='service1', dependencies=[])
        service2 = Bunch(name='service2', dependencies=[])
        context = RunningContext({'service1': service1, 'service2': service2},
                                 collection, Options(False, 'the-network', 50))
        agents = list(context.service_agents.values())
        assert not context.done
        agents[0].status = 'in-progress'
        assert not context.done
        agents[0].status = agents[1].status = 'started'
        assert context.done

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
        self.docker = FakeDocker.Instance = FakeDocker()
        services.DockerClient = self.docker
        service_agent.DockerClient = self.docker

    def test_raise_exception_on_no_services(self):
        collection = ServiceCollection()
        class NewServiceBase(Service):
            name = "not used"
            image = "not used"
        collection._base_class = NewServiceBase
        with pytest.raises(ServiceLoadError):
            collection.load_definitions()

    def test_raise_exception_on_same_name(self):
        collection = ServiceCollection()
        class NewServiceBase(Service):
            name = "not used"
            image = "not used"

        collection._base_class = NewServiceBase
        class ServiceOne(NewServiceBase):
            name = "hello"
            image = "hello"
        class ServiceTwo(NewServiceBase):
            name = "hello"
            image = "hello"
        with pytest.raises(ServiceLoadError):
            collection.load_definitions()


    def test_raise_exception_on_circular_dependency(self):
        collection = ServiceCollection()
        class NewServiceBase(Service):
            name = "not used"
            image = "not used"
        collection._base_class = NewServiceBase
        class ServiceOne(NewServiceBase):
            name = "hello"
            image = "hello"
            dependencies = ["howareyou"]

        class ServiceTwo(NewServiceBase):
            name = "goodbye"
            image = "hello"
            dependencies = ["hello"]

        class ServiceThree(NewServiceBase):
            name = "howareyou"
            image = "hello"
            dependencies = ["goodbye"]

        with pytest.raises(ServiceLoadError):
            collection.load_definitions()


    def test_load_services(self):
        collection = ServiceCollection()
        class NewServiceBase(Service):
            name = "not used"
            image = "not used"
        collection._base_class = NewServiceBase
        class ServiceOne(NewServiceBase):
            name = "hello"
            image = "hello"
            dependencies = ["howareyou"]

        class ServiceTwo(NewServiceBase):
            name = "goodbye"
            image = "hello"
            dependencies = ["hello"]

        class ServiceThree(NewServiceBase):
            name = "howareyou"
            image = "hello"

        collection.load_definitions()
        assert len(collection) == 3


    def test_exclude_for_start(self):
        collection = ServiceCollection()
        class NewServiceBase(Service):
            name = "not used"
            image = "not used"
        collection._base_class = NewServiceBase
        class ServiceOne(NewServiceBase):
            name = "hello"
            image = "hello"
            dependencies = ["howareyou"]

        class ServiceTwo(NewServiceBase):
            name = "goodbye"
            image = "hello"
            dependencies = ["hello"]

        class ServiceThree(NewServiceBase):
            name = "howareyou"
            image = "hello"

        collection.load_definitions()
        collection.exclude_for_start(['goodbye'])
        assert len(collection) == 2


    def test_error_on_start_dependency_excluded(self):
        collection = ServiceCollection()
        class NewServiceBase(Service):
            name = "not used"
            image = "not used"
        collection._base_class = NewServiceBase
        class ServiceOne(NewServiceBase):
            name = "hello"
            image = "hello"
            dependencies = ["howareyou"]

        class ServiceTwo(NewServiceBase):
            name = "goodbye"
            image = "hello"
            dependencies = ["hello"]

        class ServiceThree(NewServiceBase):
            name = "howareyou"
            image = "hello"

        collection.load_definitions()
        with pytest.raises(ServiceLoadError):
            collection.exclude_for_start(['hello'])

    def test_error_on_stop_dependency_excluded(self):
        collection = ServiceCollection()
        class NewServiceBase(Service):
            name = "not used"
            image = "not used"
        collection._base_class = NewServiceBase
        class ServiceOne(NewServiceBase):
            name = "hello"
            image = "hello"
            dependencies = ["howareyou"]

        class ServiceTwo(NewServiceBase):
            name = "goodbye"
            image = "hello"
            dependencies = ["hello"]

        class ServiceThree(NewServiceBase):
            name = "howareyou"
            image = "hello"

        collection.load_definitions()
        with pytest.raises(ServiceLoadError):
            collection.exclude_for_stop(['goodbye'])


    def test_start_all(self):
        # This test does not fake threading, which is somehow dangerous, but the
        # aim is to make sure that the error handling etc. works also when there
        # is an exception in the service agent thread, and the
        # collection.start_all method does not hang.
        collection = ServiceCollection()
        class NewServiceBase(Service):
            name = "not used"
            image = "not used"
        collection._base_class = NewServiceBase
        class ServiceOne(NewServiceBase):
            name = "hello"
            image = "hello/image"
            dependencies = ["howareyou"]

        class ServiceTwo(NewServiceBase):
            name = "goodbye"
            image = "goodbye/image"
            dependencies = ["hello"]

        class ServiceThree(NewServiceBase):
            name = "howareyou"
            image = "howareyou/image"
        collection.load_definitions()
        retval = collection.start_all(Options(False, 'the-network', 50))
        assert set(retval) == {"hello", "goodbye", "howareyou"}
        assert len(self.docker._services_started) == 3
        # The one without dependencies should have been started first
        name_prefix, service, network_name = self.docker._services_started[0]
        assert service.image == 'howareyou/image'
        assert name_prefix == "howareyou-drillmaster"


    def test_stop_on_fail(self):
        collection = ServiceCollection()
        class NewServiceBase(Service):
            name = "not used"
            image = "not used"
        class TheService(NewServiceBase):
            name = "howareyou"
            image = "howareyou/image"
            def ping(self):
                raise ValueError("I failed miserably")
        collection._base_class = NewServiceBase
        collection.load_definitions()
        collection.start_all(Options(False, 'the-network', 50))
        assert collection.failed


    @patch('drillmaster.services.threading')
    def test_start_next_lock_call(self, mock_threading):
        collection = ServiceCollection()
        class NewServiceBase(Service):
            name = "not used"
            image = "not used"

        class ServiceOne(NewServiceBase):
            name = "service1"
            image = "howareyou/image"

        class ServiceTwo(NewServiceBase):
            name = "service2"
            image = "howareyou/image"
            dependencies = ['service1']

        class ServiceThree(NewServiceBase):
            name = "service3"
            image = "howareyou/image"
            dependencies = ['service1']

        collection._base_class = NewServiceBase
        collection.load_definitions()
        collection.start_all(Options(False, 'the-network', 50))
        mock_lock = mock_threading.Lock.return_value
        # This has to be 3 because start_next is called after each service
        assert mock_lock.__enter__.call_count == 3


    def test_stop_all_remove_false(self):
        class FakeContainer(Bunch):
            def stop(self, timeout):
                self.stopped = True
                self.timeout = timeout
            def remove(self):
                self.removed = True
        container1 = FakeContainer(name='service1-drillmaster-1234',
                                   stopped=False,
                                   removed=False,
                                   network='the-network',
                                   status='running')
        container2 = FakeContainer(name='service2-drillmaster-5678',
                                   stopped=False,
                                   removed=False,
                                   network='the-network',
                                   status='exited')
        self.docker._existing_containers = [container1, container2]
        collection = ServiceCollection()
        class NewServiceBase(Service):
            name = "not used"
            image = "not used"

        class ServiceOne(NewServiceBase):
            name = "service1"
            image = "howareyou/image"

        class ServiceTwo(NewServiceBase):
            name = "service2"
            image = "howareyou/image"

        collection._base_class = NewServiceBase
        collection.load_definitions()
        collection.stop_all(StopOptions('the-network', False, 50))
        assert container1.stopped
        assert container1.timeout == 50
        assert not container2.stopped

    def test_stop_without_remove(self):
        container1 = FakeContainer(name='service1-drillmaster-1234',
                                   network='the-network',
                                   status='running')
        container2 = FakeContainer(name='service2-drillmaster-5678',
                                   network='the-network',
                                   status='exited')
        self.docker._existing_containers = [container1, container2]
        collection = ServiceCollection()
        class NewServiceBase(Service):
            name = "not used"
            image = "not used"

        class ServiceOne(NewServiceBase):
            name = "service1"
            image = "howareyou/image"

        class ServiceTwo(NewServiceBase):
            name = "service2"
            image = "howareyou/image"

        collection._base_class = NewServiceBase
        collection.load_definitions()
        collection.stop_all(StopOptions('the-network', False, 50))
        assert container1.stopped
        assert container1.timeout == 50
        assert container1.removed_at is None
        assert not container2.stopped
        assert self.docker._networks_removed == []


    def test_stop_with_remove_and_order(self):
        container1 = FakeContainer(name='service1-drillmaster-1234',
                                   network='the-network',
                                   status='running')
        container2 = FakeContainer(name='service2-drillmaster-5678',
                                   network='the-network',
                                   status='running')
        container3 = FakeContainer(name='service3-drillmaster-5678',
                                   network='the-network',
                                   status='running')
        self.docker._existing_containers = [container1, container2, container3]
        collection = ServiceCollection()
        class NewServiceBase(Service):
            name = "not used"
            image = "not used"

        class ServiceOne(NewServiceBase):
            name = "service1"
            image = "howareyou/image"

        class ServiceTwo(NewServiceBase):
            name = "service2"
            image = "howareyou/image"
            dependencies = ['service1']

        class ServiceThree(NewServiceBase):
            name = "service3"
            image = "howareyou/image"
            dependencies = ['service2']

        collection._base_class = NewServiceBase
        collection.load_definitions()
        collection.stop_all(StopOptions('the-network', True, 50))
        assert container1.stopped
        assert container1.removed_at is not None
        assert container2.stopped
        assert container2.removed_at is not None
        assert container3.stopped
        assert container3.removed_at is not None
        assert container1.removed_at > container2.removed_at > container3.removed_at
        assert self.docker._networks_removed == ['the-network']

class ServiceCommandTests(unittest.TestCase):

    def setUp(self):
        self.docker = FakeDocker.Instance = FakeDocker()
        services.DockerClient = self.docker
        class MockServiceCollection:
            def load_definitions(self):
                pass
            def exclude_for_start(self, exclude):
                self.excluded = exclude
            def exclude_for_stop(self, exclude):
                self.excluded = exclude
            def start_all(self, options):
                self.options = options
                return ["one", "two"]
            def stop_all(self, options):
                self.options = options
                self.stopped = True
        self.collection = MockServiceCollection()
        services.ServiceCollection = lambda: self.collection

    def test_start_service_create_network(self):
        services.start_services(False, [], "drillmaster", 50)
        assert self.docker._networks_created == ["drillmaster"]

    def test_start_service_exclude(self):
        services.start_services(True, ['blah'], "drillmaster", 50)
        assert self.collection.excluded == ['blah']
        assert self.collection.options.run_new_containers

    def test_stop_services(self):
        services.stop_services(['test'], "drillmaster", False, 50)
        assert self.collection.options.network_name == 'drillmaster'
        assert self.collection.options.timeout == 50
        assert not self.collection.options.remove
        assert self.collection.excluded == ['test']
