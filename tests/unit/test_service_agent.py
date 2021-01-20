import unittest
from unittest.mock import patch
from types import SimpleNamespace as Bunch
from datetime import datetime

import attr
import pytest

from miniboss import types
from miniboss import service_agent, context
from miniboss.services import connect_services
from miniboss.service_agent import (ServiceAgent,
                                    AgentStatus,
                                    Actions,
                                    ServiceAgentException)
from miniboss.types import Options, Network, RunCondition

from common import FakeDocker, FakeService, FakeRunningContext, FakeContainer, DEFAULT_OPTIONS


class ServiceAgentTests(unittest.TestCase):

    def setUp(self):
        self.docker = FakeDocker.Instance = FakeDocker({'the-network': 'the-network-id'})
        service_agent.DockerClient = self.docker
        types.set_group_name('testing')

    def tearDown(self):
        types._unset_group_name()

    def test_can_start(self):
        services = connect_services([Bunch(name='service1', dependencies=[]),
                                     Bunch(name='service2', dependencies=['service1'])])
        agent = ServiceAgent(services['service2'], DEFAULT_OPTIONS, None)
        assert agent.can_start is False
        agent.process_service_started(services['service1'])
        assert agent.can_start is True
        agent.status = AgentStatus.IN_PROGRESS
        assert agent.can_start is False

    def test_can_stop(self):
        services = connect_services([Bunch(name='service1', dependencies=[]),
                                     Bunch(name='service2', dependencies=['service1'])])
        agent = ServiceAgent(services['service1'], DEFAULT_OPTIONS, None)
        assert agent.can_stop is False
        agent.process_service_stopped(services['service2'])
        assert agent.can_stop is True


    def test_action_property(self):
        service = Bunch(name='service1', dependencies=[], dependants=[])
        agent = ServiceAgent(service, DEFAULT_OPTIONS, None)
        assert agent.action is None
        with pytest.raises(ServiceAgentException):
            agent.action = 'blah'
        agent.action = 'start'
        assert agent.action == 'start'

    def test_fail_if_action_not_set(self):
        service = Bunch(name='service1', dependencies=[], dependants=[])
        fake_context = FakeRunningContext()
        agent = ServiceAgent(service, DEFAULT_OPTIONS, fake_context)
        with pytest.raises(ServiceAgentException):
            agent.run()
        assert len(fake_context.failed_services) == 1
        assert fake_context.failed_services[0] is service

    def test_run_image(self):
        agent = ServiceAgent(FakeService(), DEFAULT_OPTIONS, None)
        agent.run_image()
        assert len(self.docker._services_started) == 1
        prefix, service, network = self.docker._services_started[0]
        assert prefix == "service1-testing"
        assert service.name == 'service1'
        assert service.image == 'not/used'
        assert network.name == 'the-network'


    def test_run_image_extrapolate_env(self):
        service = FakeService()
        service.env = {'ENV_ONE': 'http://{host}:{port:d}'}
        context.Context['host'] = 'zombo.com'
        context.Context['port'] = 80
        agent = ServiceAgent(service, DEFAULT_OPTIONS, None)
        agent.run_image()
        assert len(self.docker._services_started) == 1
        _, service, _ = self.docker._services_started[0]
        assert service.env['ENV_ONE'] == 'http://zombo.com:80'


    def test_agent_status_change_happy_path(self):
        class ServiceAgentTestSubclass(ServiceAgent):
            def ping(self):
                assert self.status == 'in-progress'
                return super().ping()
        agent = ServiceAgentTestSubclass(FakeService(),
                                         DEFAULT_OPTIONS,
                                         FakeRunningContext())
        assert agent.status == 'null'
        agent.start_service()
        agent.join()
        assert agent.status == 'started'


    def test_agent_status_change_sad_path(self):
        class ServiceAgentTestSubclass(ServiceAgent):
            def ping(self):
                assert self.status == 'in-progress'
                raise ValueError("I failed miserably")
        agent = ServiceAgentTestSubclass(FakeService(), DEFAULT_OPTIONS, FakeRunningContext())
        assert agent.status == 'null'
        agent.start_service()
        agent.join()
        assert agent.status == 'failed'


    def test_skip_if_running_on_same_network(self):
        service = FakeService()
        agent = ServiceAgent(service, DEFAULT_OPTIONS, None)
        self.docker._existing_containers = [Bunch(status='running',
                                                  name="{}-testing-123".format(service.name),
                                                  network='the-network')]
        agent.run_image()
        assert len(self.docker._services_started) == 0
        assert len(self.docker._existing_queried) == 1
        assert self.docker._existing_queried[0] == ("service1-testing",
                                                    Network(name="the-network", id="the-network-id"))


    def test_start_old_container_if_exists(self):
        service = FakeService()
        agent = ServiceAgent(service, DEFAULT_OPTIONS, None)
        self.docker._existing_containers = [Bunch(status='exited',
                                                  network='the-network',
                                                  id='longass-container-id',
                                                  image=Bunch(tags=[service.image]),
                                                  attrs={'Config': {'Env': []}},
                                                  name="{}-testing-123".format(service.name))]
        agent.run_image()
        assert len(self.docker._services_started) == 0
        assert self.docker._containers_ran == ['longass-container-id']


    def test_start_new_container_if_old_has_different_tag(self):
        service = FakeService()
        agent = ServiceAgent(service, DEFAULT_OPTIONS, None)
        self.docker._existing_containers = [Bunch(status='exited',
                                                  network='the-network',
                                                  id='longass-container-id',
                                                  image=Bunch(tags=['different-tag']),
                                                  attrs={'Config': {'Env': []}},
                                                  name="{}-miniboss-123".format(service.name))]
        agent.run_image()
        assert len(self.docker._services_started) == 1
        prefix, service, network = self.docker._services_started[0]
        assert prefix == "service1-testing"
        assert service.name == 'service1'
        assert service.image == 'not/used'
        assert network.name == 'the-network'
        assert self.docker._containers_ran == []


    def test_start_new_container_if_differing_env_value(self):
        service = FakeService()
        service.env = {'KEY': 'some-value'}
        agent = ServiceAgent(service, DEFAULT_OPTIONS, None)
        self.docker._existing_containers = [Bunch(status='exited',
                                                  network='the-network',
                                                  id='longass-container-id',
                                                  image=Bunch(tags=[service.image]),
                                                  attrs={'Config': {'Env': ['KEY=other-value']}},
                                                  name="{}-miniboss-123".format(service.name))]
        agent.run_image()
        assert len(self.docker._services_started) == 1
        prefix, service, network = self.docker._services_started[0]
        assert prefix == "service1-testing"
        assert service.name == 'service1'
        assert service.image == 'not/used'
        assert network.name == 'the-network'
        assert self.docker._containers_ran == []


    def test_start_existing_if_differing_env_value_type_but_not_string(self):
        service = FakeService()
        service.env = {'KEY': 12345}
        agent = ServiceAgent(service, DEFAULT_OPTIONS, None)
        self.docker._existing_containers = [Bunch(status='exited',
                                                  network='the-network',
                                                  id='longass-container-id',
                                                  image=Bunch(tags=[service.image]),
                                                  attrs={'Config': {'Env': ['KEY=12345']}},
                                                  name="{}-testing-123".format(service.name))]
        agent.run_image()
        assert len(self.docker._services_started) == 0


    def test_start_new_if_always_start_new(self):
        service = FakeService()
        service.always_start_new = True
        options = Options(network=Network(name='the-network', id='the-network-id'),
                          timeout=1,
                          remove=True,
                          run_dir='/etc',
                          build=[])
        agent = ServiceAgent(service, options, None)
        restarted = False
        def start():
            nonlocal restarted
            restarted = True
        self.docker._existing_containers = [Bunch(status='exited',
                                                  start=start,
                                                  network='the-network',
                                                  attrs={'Config': {'Env': []}},
                                                  name="{}-miniboss-123".format(service.name))]
        agent.run_image()
        assert len(self.docker._services_started) == 1
        assert not restarted

    def test_build_on_start(self):
        fake_context = FakeRunningContext()
        fake_service = FakeService()
        fake_service.build_from_directory = "the/service/dir"
        options = attr.evolve(DEFAULT_OPTIONS, build=[fake_service.name])
        agent = ServiceAgent(fake_service, options, fake_context)
        agent.start_service()
        agent.join()
        assert len(self.docker._images_built) == 1


    def test_pre_start_before_run(self):
        fake_context = FakeRunningContext()
        fake_service = FakeService()
        assert not fake_service.pre_start_called
        agent = ServiceAgent(fake_service, DEFAULT_OPTIONS, fake_context)
        agent.start_service()
        agent.join()
        assert fake_service.pre_start_called


    def test_ping_and_init_after_run(self):
        fake_context = FakeRunningContext()
        fake_service = FakeService()
        agent = ServiceAgent(fake_service, DEFAULT_OPTIONS, fake_context)
        agent.start_service()
        agent.join()
        assert len(fake_context.started_services) == 1
        assert fake_context.started_services[0].name == 'service1'
        assert fake_service.ping_count == 1
        assert fake_service.init_called


    def test_no_pre_ping_or_init_if_running(self):
        service = FakeService()
        fake_context = FakeRunningContext()
        options = Options(network=Network(name='the-network', id='the-network-id'),
                          timeout=1,
                          remove=True,
                          run_dir='/etc',
                          build=[])
        agent = ServiceAgent(service, options, fake_context)
        self.docker._existing_containers = [Bunch(status='running',
                                                  network='the-network',
                                                  name="{}-testing-123".format(service.name))]
        agent.start_service()
        agent.join()
        assert service.ping_count == 0
        assert not service.init_called
        assert not service.pre_start_called


    def test_yes_ping_no_init_if_started(self):
        service = FakeService()
        fake_context = FakeRunningContext()
        agent = ServiceAgent(service, DEFAULT_OPTIONS, fake_context)
        self.docker._existing_containers = [Bunch(status='exited',
                                                  network='the-network',
                                                  id='longass-container-id',
                                                  image=Bunch(tags=[service.image]),
                                                  attrs={'Config': {'Env': []}},
                                                  name="{}-testing-123".format(service.name))]
        agent.start_service()
        agent.join()
        assert service.ping_count == 1
        assert not service.init_called
        assert self.docker._containers_ran == ['longass-container-id']


    @patch('miniboss.service_agent.time')
    def test_repeat_ping_and_timeout(self, mock_time):
        mock_time.monotonic.side_effect = [0, 0.2, 0.6, 0.8, 1]
        fake_context = FakeRunningContext()
        fake_service = FakeService(fail_ping=True)
        agent = ServiceAgent(fake_service, DEFAULT_OPTIONS, fake_context)
        agent.start_service()
        agent.join()
        assert fake_service.ping_count == 3
        assert mock_time.sleep.call_count == 3
        assert agent.status == AgentStatus.FAILED
        assert len(fake_context.failed_services) == 1
        assert fake_context.failed_services[0] is fake_service


    def test_service_failed_on_failed_ping(self):
        fake_context = FakeRunningContext()
        fake_service = FakeService(fail_ping=True)
        # Using options with low timeout so that test doesn't hang
        options = Options(network=Network(name='the-network', id='the-network-id'),
                          timeout=0.1,
                          remove=True,
                          run_dir='/etc',
                          build=[])
        agent = ServiceAgent(fake_service, options, fake_context)
        agent.start_service()
        agent.join()
        assert fake_service.ping_count > 0
        assert fake_context.started_services == []
        assert len(fake_context.failed_services) == 1
        assert fake_context.failed_services[0].name == 'service1'


    def test_stop_remove_container_on_failed(self):
        fake_context = FakeRunningContext()
        name = 'aservice'
        container = FakeContainer(name='{}-testing-5678'.format(name),
                                  network='the-network',
                                  status='running')
        _context = self
        class CrazyFakeService(FakeService):
            def ping(self):
                _context.docker._existing_containers = [container]
                raise ValueError("Blah")
        options = Options(network=Network(name='the-network', id='the-network-id'),
                          timeout=0.01,
                          remove=True,
                          run_dir='/etc',
                          build=[])
        agent = ServiceAgent(CrazyFakeService(name=name), options, fake_context)
        agent.start_service()
        agent.join()
        assert container.stopped
        assert container.removed_at is not None
        # This is 0 because the service wasn't stopped by the user
        assert len(fake_context.stopped_services) == 0


    def test_call_collection_failed_on_error(self):
        fake_context = FakeRunningContext()
        fake_service = FakeService(exception_at_init=ValueError)
        agent = ServiceAgent(fake_service, DEFAULT_OPTIONS, fake_context)
        agent.start_service()
        agent.join()
        assert fake_service.ping_count > 0
        assert fake_context.started_services == []
        assert len(fake_context.failed_services) == 1
        assert fake_context.failed_services[0].name == 'service1'


    def test_stop_container_does_not_exist(self):
        fake_context = FakeRunningContext()
        fake_service = FakeService(exception_at_init=ValueError)
        agent = ServiceAgent(fake_service, DEFAULT_OPTIONS, fake_context)
        agent.stop_service()
        agent.join()
        assert agent.status == AgentStatus.STOPPED


    def test_stop_existing_container(self):
        fake_context = FakeRunningContext()
        fake_service = FakeService(exception_at_init=ValueError)
        container = FakeContainer(name='{}-testing-5678'.format(fake_service.name),
                                  network='the-network',
                                  status='running')
        self.docker._existing_containers = [container]
        agent = ServiceAgent(fake_service, DEFAULT_OPTIONS, fake_context)
        agent.stop_service()
        agent.join()
        assert agent.status == AgentStatus.STOPPED
        assert container.stopped
        assert len(fake_context.stopped_services) == 1
        assert fake_context.stopped_services[0] is fake_service


    @patch("miniboss.service_agent.datetime")
    def test_build_image(self, mock_datetime):
        now = datetime.now()
        mock_datetime.now.return_value = now
        fake_service = FakeService(name='myservice')
        fake_service.build_from_directory = "the/service/dir"
        agent = ServiceAgent(fake_service, DEFAULT_OPTIONS, FakeRunningContext())
        retval = agent.build_image()
        assert len(self.docker._images_built) == 1
        build_dir, dockerfile, image_tag = self.docker._images_built[0]
        assert build_dir == "/etc/the/service/dir"
        assert dockerfile == 'Dockerfile'
        assert image_tag == now.strftime("myservice-miniboss-%Y-%m-%d-%H%M")
        assert retval == image_tag
        assert RunCondition.BUILD_IMAGE in agent.run_condition.actions


    def test_build_image_dockerfile(self):
        fake_service = FakeService(name='myservice')
        fake_service.dockerfile = 'Dockerfile.other'
        fake_service.build_from_directory = "the/service/dir"
        agent = ServiceAgent(fake_service, DEFAULT_OPTIONS, FakeRunningContext())
        agent.build_image()
        assert len(self.docker._images_built) == 1
        _, dockerfile, _ = self.docker._images_built[0]
        assert dockerfile == 'Dockerfile.other'
