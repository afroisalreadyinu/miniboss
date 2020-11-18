import os
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace as Bunch
import tempfile
import pathlib

import pytest

from miniboss.services import (connect_services,
                               Service,
                               ServiceLoadError,
                               ServiceCollection,
                               ServiceDefinitionError)

from miniboss.service_agent import ServiceAgent
from miniboss.types import Options, Network
from miniboss import services, service_agent, Context

from common import FakeDocker, FakeContainer

DEFAULT_OPTIONS = Options(Network('the-network', 'the-network-id'), 50, False, "/etc")

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

        with pytest.raises(ServiceDefinitionError):
            class NewService(Service):
                name = "yes"
                image = "yes"
                env = {}
                always_start_new = 123

    def test_invalid_signal_name(self):
        with pytest.raises(ServiceDefinitionError):
            class NewService(Service):
                name = "yes"
                image = "yes"
                env = {}
                stop_signal = "HELLO"

    def test_hashable(self):
        class NewService(Service):
            name = "service_one"
            image = "notused"
        service = NewService()
        a_dict = {service: "one"}
        assert service == NewService()
        assert a_dict[NewService()] == "one"

    def test_invalid_build_from_directory(self):
        with pytest.raises(ServiceDefinitionError):
            class NewService(Service):
                name = "yes"
                image = "yes"
                env = {}
                build_from_directory = 123

    def test_invalid_dockerfile(self):
        with pytest.raises(ServiceDefinitionError):
            class NewService(Service):
                name = "yes"
                image = "yes"
                env = {}
                dockerfile = 567

    def test_volume_spec(self):
        with pytest.raises(ServiceDefinitionError):
            class NewService(Service):
                name = "yes"
                image = "yes"
                volumes = ["vol1", 123]

        with pytest.raises(ServiceDefinitionError):
            class NewService(Service):
                name = "yes"
                image = "yes"
                volumes = {"vol1": 123}

        with pytest.raises(ServiceDefinitionError):
            class NewService(Service):
                name = "yes"
                image = "yes"
                volumes = {"vol1": {'key': 'value'}}

        with pytest.raises(ServiceDefinitionError):
            class NewService(Service):
                name = "yes"
                image = "yes"
                volumes = {"vol1": {'bind': 12345}}


    def test_volume_def_to_binds(self):
        class NewService(Service):
            name = "yes"
            image = "yes"
            volumes = {"/home/user/temp": {'bind': "/mnt/vol1", "mode": "ro"}}
        assert NewService().volume_def_to_binds() == ["/mnt/vol1"]

        class NewService(Service):
            name = "yes"
            image = "yes"
            volumes = ["/tmp/dir1:/mnt/vol1", "/tmp/dir2:/mnt/vol2:ro"]
        assert NewService().volume_def_to_binds() == ["/mnt/vol1", "/mnt/vol2"]


class ConnectServicesTests(unittest.TestCase):

    def test_raise_exception_on_same_name(self):
        services = [Bunch(name="hello", image="hello"),
                    Bunch(name="hello", image="goodbye")]
        with pytest.raises(ServiceLoadError):
            connect_services(services)

    def test_exception_on_invalid_dependency(self):
        services = [Bunch(name="hello", image="hello", dependencies=[]),
                    Bunch(name="goodbye", image="goodbye", dependencies=["not_hello"])]
        with pytest.raises(ServiceLoadError):
            connect_services(services)

    def test_all_good(self):
        services = [Bunch(name="hello", image="hello", dependencies=[]),
                    Bunch(name="goodbye", image="goodbye", dependencies=["hello"]),
                    Bunch(name="howareyou", image="howareyou", dependencies=["hello", "goodbye"])]
        by_name = connect_services(services)
        assert len(by_name) == 3
        hello = by_name['hello']
        assert hello.dependencies == []
        assert len(hello.dependants) == 2
        assert by_name['goodbye'] in hello.dependants
        assert by_name['howareyou'] in hello.dependants
        howareyou = by_name['howareyou']
        assert len(howareyou.dependencies) == 2
        assert hello in howareyou.dependencies
        assert by_name['goodbye'] in howareyou.dependencies
        assert howareyou.dependants == []


class ServiceCollectionTests(unittest.TestCase):

    def setUp(self):
        self.docker = FakeDocker.Instance = FakeDocker({'the-network': 'the-network-id'})
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


    def test_start_dependency_and_dependant_excluded(self):
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
        # There shouldn't be an exception, since we are excluding both hello and
        # goodbye
        collection.exclude_for_start(['hello', 'goodbye'])


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


    def test_stop_dependency_and_dependant_excluded(self):
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
        collection.exclude_for_stop(['howareyou', 'hello'])


    def test_populate_dependants(self):
        collection = ServiceCollection()
        class NewServiceBase(Service):
            name = "not used"
            image = "not used"
        collection._base_class = NewServiceBase

        class ServiceOne(NewServiceBase):
            name = "hello"
            image = "not/used"
            dependencies = ["howareyou"]

        class ServiceTwo(NewServiceBase):
            name = "goodbye"
            image = "not/used"
            dependencies = ["hello", "howareyou"]

        class ServiceThree(NewServiceBase):
            name = "howareyou"
            image = "not/used"
        collection.load_definitions()
        assert len(collection.all_by_name) == 3
        hello = collection.all_by_name['hello']
        assert len(hello.dependants) == 1
        assert hello.dependants[0].name == 'goodbye'
        howareyou = collection.all_by_name['howareyou']
        assert len(howareyou.dependants) == 2
        names = [x.name for x in howareyou.dependants]
        assert 'hello' in names
        assert 'goodbye' in names


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
        retval = collection.start_all(DEFAULT_OPTIONS)
        assert set(retval) == {"hello", "goodbye", "howareyou"}
        assert len(self.docker._services_started) == 3
        # The one without dependencies should have been started first
        name_prefix, service, network_name = self.docker._services_started[0]
        assert service.image == 'howareyou/image'
        assert name_prefix == "howareyou-miniboss"


    def test_start_all_with_build(self):
        collection = ServiceCollection()
        class NewServiceBase(Service):
            name = "not used"
            image = "not used"
        collection._base_class = NewServiceBase
        class ServiceTwo(NewServiceBase):
            name = "goodbye"
            image = "goodbye/image"
            build_from_directory = "goodbye/dir"
            dockerfile = "Dockerfile.alt"
        collection.load_definitions()
        retval = collection.start_all(DEFAULT_OPTIONS, build='goodbye')
        assert len(self.docker._images_built) == 1
        build_dir, dockerfile, image_tag = self.docker._images_built[0]
        assert build_dir == "/etc/goodbye/dir"
        assert dockerfile == 'Dockerfile.alt'
        assert image_tag.startswith("goodbye-miniboss")
        service = collection.all_by_name['goodbye']
        assert service.image == image_tag


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
        started = collection.start_all(DEFAULT_OPTIONS)
        assert started == []


    def test_dont_return_failed_services(self):
        collection = ServiceCollection()
        class NewServiceBase(Service):
            name = "not used"
            image = "not used"

        class TheFirstService(NewServiceBase):
            name = "howareyou"
            image = "howareyou/image"

        class TheService(NewServiceBase):
            name = "imok"
            image = "howareyou/image"
            dependencies = ["howareyou"]
            def ping(self):
                raise ValueError("I failed miserably")

        collection._base_class = NewServiceBase
        collection.load_definitions()
        started = collection.start_all(DEFAULT_OPTIONS)
        assert started == ["howareyou"]


    def test_stop_all_remove_false(self):
        container1 = FakeContainer(name='service1-miniboss-1234',
                                   stopped=False,
                                   network='the-network',
                                   status='running')
        container2 = FakeContainer(name='service2-miniboss-5678',
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
        collection.stop_all(DEFAULT_OPTIONS)
        assert container1.stopped
        assert container1.timeout == 50
        assert not container2.stopped

    def test_stop_without_remove(self):
        container1 = FakeContainer(name='service1-miniboss-1234',
                                   network='the-network',
                                   status='running')
        container2 = FakeContainer(name='service2-miniboss-5678',
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
        collection.stop_all(DEFAULT_OPTIONS)
        assert container1.stopped
        assert container1.timeout == 50
        assert container1.removed_at is None
        assert not container2.stopped
        assert self.docker._networks_removed == []


    def test_stop_with_remove_and_order(self):
        container1 = FakeContainer(name='service1-miniboss-1234',
                                   network='the-network',
                                   status='running')
        container2 = FakeContainer(name='service2-miniboss-5678',
                                   network='the-network',
                                   status='running')
        container3 = FakeContainer(name='service3-miniboss-5678',
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
        collection.stop_all(Options(Network('the-network', 'the-network-id'), 50, True, "/etc"))
        assert container1.stopped
        assert container1.removed_at is not None
        assert container2.stopped
        assert container2.removed_at is not None
        assert container3.stopped
        assert container3.removed_at is not None
        assert container1.removed_at > container2.removed_at > container3.removed_at
        assert self.docker._networks_removed == ['the-network']


    def test_stop_with_remove_and_exclude(self):
        container1 = FakeContainer(name='service1-miniboss-1234',
                                   network='the-network',
                                   status='running')
        container2 = FakeContainer(name='service2-miniboss-5678',
                                   network='the-network',
                                   status='running')
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
        collection.exclude_for_stop(['service2'])
        collection.stop_all(Options(Network('the-network', 'the-network-id'), 50, True, '/etc'))
        assert container1.stopped
        assert container1.removed_at is not None
        # service2 was excluded
        assert not container2.stopped
        assert container2.removed_at is None
        # If excluded is not empty, network should not be removed
        assert self.docker._networks_removed == []


    def test_update_for_base_service(self):
        container1 = FakeContainer(name='service1-miniboss-1234',
                                   network='the-network',
                                   status='running')
        container2 = FakeContainer(name='service2-miniboss-5678',
                                   network='the-network',
                                   status='running')
        container3 = FakeContainer(name='service3-miniboss-5678',
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
            name = 'service3'
            image = 'howareyou/image'
            dependencies = ['service1', 'service2']

        collection._base_class = NewServiceBase
        collection.load_definitions()
        collection.update_for_base_service('service2')
        assert collection.all_by_name == {'service2': ServiceTwo(),
                                          'service3': ServiceThree()}
        collection.stop_all(DEFAULT_OPTIONS)
        assert not container1.stopped
        assert container2.stopped
        assert container3.stopped


    def test_check_can_be_built(self):
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
            build_from_directory = "the/service/dir"

        collection._base_class = NewServiceBase
        collection.load_definitions()
        with pytest.raises(ServiceDefinitionError):
            collection.check_can_be_built('no-such-service')
        with pytest.raises(ServiceDefinitionError):
            collection.check_can_be_built('service1')
        collection.check_can_be_built('service2')


class ServiceCommandTests(unittest.TestCase):

    def setUp(self):
        self.docker = FakeDocker.Instance = FakeDocker({'miniboss': 'minibos-network-id'})
        services.DockerClient = self.docker
        class MockServiceCollection:
            def load_definitions(self):
                pass
            def exclude_for_start(self, exclude):
                self.excluded = exclude
            def exclude_for_stop(self, exclude):
                self.excluded = exclude
            def start_all(self, options, build=None):
                self.options = options
                self.built = build
                return ["one", "two"]
            def stop_all(self, options):
                self.options = options
                self.stopped = True
            def reload_service(self, service_name, options):
                self.options = options
                self.reloaded = service_name
            def check_can_be_built(self, service_name):
                self.checked_can_be_built = service_name
            def update_for_base_service(self, service_name):
                self.updated_for_base_service = service_name

        self.collection = MockServiceCollection()
        services.ServiceCollection = lambda: self.collection
        Context._reset()

    def test_start_services_create_network(self):
        services.start_services('/tmp', [], "miniboss", 50)
        assert self.docker._networks_created == ["miniboss"]

    def test_start_services_exclude(self):
        services.start_services("/tmp", ['blah'], "miniboss", 50)
        assert self.collection.excluded == ['blah']

    def test_start_services_save_context(self):
        directory = tempfile.mkdtemp()
        Context['key_one'] = 'a_value'
        Context['key_two'] = 'other_value'
        services.start_services(directory, [], "miniboss", 50)
        with open(os.path.join(directory, ".miniboss-context"), "r") as context_file:
            context_data = json.load(context_file)
        assert context_data == {'key_one': 'a_value', 'key_two': 'other_value'}

    def test_load_context_on_new(self):
        directory = tempfile.mkdtemp()
        with open(os.path.join(directory, ".miniboss-context"), "w") as context_file:
            context_file.write(json.dumps({"key_one": "value_one", "key_two": "value_two"}))
        services.start_services(directory, [], "miniboss", 50)
        assert Context['key_one'] == 'value_one'
        assert Context['key_two'] == 'value_two'

    def test_stop_services(self):
        services.stop_services('/tmp', ['test'], "miniboss", False, 50)
        assert self.collection.options.network.name == 'miniboss'
        assert self.collection.options.timeout == 50
        assert self.collection.options.run_dir == '/tmp'
        assert not self.collection.options.remove
        assert self.collection.excluded == ['test']

    def test_stop_services_remove_context(self):
        directory = tempfile.mkdtemp()
        path = pathlib.Path(directory) / ".miniboss-context"
        with open(path, "w") as context_file:
            context_file.write(json.dumps({"key_one": "value_one", "key_two": "value_two"}))
        services.stop_services(directory, [], "miniboss", False, 50)
        assert path.exists()
        services.stop_services(directory, [], "miniboss", True, 50)
        assert not path.exists()

    def test_reload_service(self):
        services.reload_service('/tmp', 'the-service', "miniboss", False, 50)
        assert self.collection.checked_can_be_built == 'the-service'
        assert self.collection.updated_for_base_service == 'the-service'
        assert self.collection.options.network.name == 'miniboss'
        assert self.collection.options.timeout == 50
        assert self.collection.options.run_dir == '/tmp'
        assert self.collection.built == 'the-service'
        assert not self.collection.options.remove


    def test_reload_service_save_and_load_context(self):
        directory = tempfile.mkdtemp()
        path = pathlib.Path(directory) / ".miniboss-context"
        with open(path, "w") as context_file:
            context_file.write(json.dumps({"key_one": "value_one",
                                           "key_two": "value_two"}))
        services.reload_service(directory, 'the-service', "miniboss", False, 50)
        assert Context['key_one'] == 'value_one'
        assert Context['key_two'] == 'value_two'
        assert path.exists()
