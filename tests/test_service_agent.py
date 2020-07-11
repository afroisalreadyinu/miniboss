import unittest
from unittest.mock import patch
from types import SimpleNamespace as Bunch

import pytest

from drillmaster import service_agent, context
from drillmaster.services import connect_services
from drillmaster.service_agent import (ServiceAgent,
                                       Options,
                                       StopOptions,
                                       AgentStatus,
                                       Actions,
                                       ServiceAgentException)

from common import FakeDocker, FakeService, FakeRunningContext, FakeContainer

DEFAULT_START_OPTIONS = Options(False, 'the-network', 1)
DEFAULT_STOP_OPTIONS = StopOptions('the-network', False, 1)

class ServiceAgentTests(unittest.TestCase):

    def setUp(self):
        self.docker = FakeDocker.Instance = FakeDocker()
        service_agent.DockerClient = self.docker


    def test_can_start(self):
        services = connect_services([Bunch(name='service1', dependencies=[]),
                                     Bunch(name='service2', dependencies=['service1'])])
        agent = ServiceAgent(services['service2'], DEFAULT_START_OPTIONS, None)
        assert agent.can_start is False
        agent.process_service_started(services['service1'])
        assert agent.can_start is True
        agent.status = AgentStatus.IN_PROGRESS
        assert agent.can_start is False

    def test_can_stop(self):
        services = connect_services([Bunch(name='service1', dependencies=[]),
                                     Bunch(name='service2', dependencies=['service1'])])
        agent = ServiceAgent(services['service1'], DEFAULT_START_OPTIONS, None)
        assert agent.can_stop is False
        agent.process_service_stopped(services['service2'])
        assert agent.can_stop is True


    def test_action_property(self):
        service = Bunch(name='service1', dependencies=[], dependants=[])
        agent = ServiceAgent(service, DEFAULT_START_OPTIONS, None)
        assert agent.action is None
        with pytest.raises(ServiceAgentException):
            agent.action = 'blah'
        agent.action = 'start'
        assert agent.action == 'start'

    def test_fail_if_action_not_set(self):
        service = Bunch(name='service1', dependencies=[], dependants=[])
        fake_context = FakeRunningContext()
        agent = ServiceAgent(service, DEFAULT_START_OPTIONS, fake_context)
        with pytest.raises(ServiceAgentException):
            agent.run()
        assert len(fake_context.failed_services) == 1
        assert fake_context.failed_services[0] is service

    def test_run_image(self):
        agent = ServiceAgent(FakeService(), DEFAULT_START_OPTIONS, None)
        agent.run_image()
        assert len(self.docker._services_started) == 1
        prefix, service, network_name = self.docker._services_started[0]
        assert prefix == "service1-drillmaster"
        assert service.name == 'service1'
        assert service.image == 'not/used'
        assert network_name == 'the-network'


    def test_run_image_extrapolate_env(self):
        service = FakeService()
        service.env = {'ENV_ONE': 'http://{host}:{port:d}'}
        context.Context['host'] = 'zombo.com'
        context.Context['port'] = 80
        agent = ServiceAgent(service, DEFAULT_START_OPTIONS, None)
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
                                         DEFAULT_START_OPTIONS,
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
        agent = ServiceAgentTestSubclass(FakeService(), DEFAULT_START_OPTIONS, FakeRunningContext())
        assert agent.status == 'null'
        agent.start_service()
        agent.join()
        assert agent.status == 'failed'


    def test_skip_if_running_on_same_network(self):
        service = FakeService()
        agent = ServiceAgent(service, DEFAULT_START_OPTIONS, None)
        self.docker._existing_containers = [Bunch(status='running',
                                                  name="{}-drillmaster-123".format(service.name),
                                                  network='the-network')]
        agent.run_image()
        assert len(self.docker._services_started) == 0
        assert len(self.docker._existing_queried) == 1
        assert self.docker._existing_queried[0] == ("service1-drillmaster", "the-network")


    def test_start_old_container_if_exists(self):
        service = FakeService()
        agent = ServiceAgent(service, DEFAULT_START_OPTIONS, None)
        self.docker._existing_containers = [Bunch(status='exited',
                                                  network='the-network',
                                                  id='longass-container-id',
                                                  name="{}-drillmaster-123".format(service.name))]
        agent.run_image()
        assert len(self.docker._services_started) == 0
        assert self.docker._containers_ran == ['longass-container-id']


    def test_start_new_if_run_new_containers(self):
        service = FakeService()
        agent = ServiceAgent(service, Options(True, 'the-network', 1), None)
        restarted = False
        def start():
            nonlocal restarted
            restarted = True
        self.docker._existing_containers = [Bunch(status='exited',
                                                  start=start,
                                                  network='the-network',
                                                  name="{}-drillmaster-123".format(service.name))]
        agent.run_image()
        assert len(self.docker._services_started) == 1
        assert not restarted


    def test_start_new_if_always_start_new(self):
        service = FakeService()
        service.always_start_new = True
        agent = ServiceAgent(service, Options(True, 'the-network', 1), None)
        restarted = False
        def start():
            nonlocal restarted
            restarted = True
        self.docker._existing_containers = [Bunch(status='exited',
                                                  start=start,
                                                  network='the-network',
                                                  name="{}-drillmaster-123".format(service.name))]
        agent.run_image()
        assert len(self.docker._services_started) == 1
        assert not restarted


    def test_ping_and_init_after_run(self):
        fake_context = FakeRunningContext()
        fake_service = FakeService()
        agent = ServiceAgent(fake_service, DEFAULT_START_OPTIONS, fake_context)
        agent.start_service()
        agent.join()
        assert len(fake_context.started_services) == 1
        assert fake_context.started_services[0].name == 'service1'
        assert fake_service.ping_count == 1
        assert fake_service.init_called


    def test_no_ping_or_init_if_running(self):
        service = FakeService()
        fake_context = FakeRunningContext()
        agent = ServiceAgent(service, Options(True, 'the-network', 1), fake_context)
        self.docker._existing_containers = [Bunch(status='running',
                                                  network='the-network',
                                                  name="{}-drillmaster-123".format(service.name))]
        agent.start_service()
        agent.join()
        assert service.ping_count == 0
        assert not service.init_called


    def test_yes_ping_no_init_if_started(self):
        service = FakeService()
        fake_context = FakeRunningContext()
        agent = ServiceAgent(service, Options(False, 'the-network', 1), fake_context)
        self.docker._existing_containers = [Bunch(status='exited',
                                                  network='the-network',
                                                  id='longass-container-id',
                                                  name="{}-drillmaster-123".format(service.name))]
        agent.start_service()
        agent.join()
        assert service.ping_count == 1
        assert not service.init_called
        assert self.docker._containers_ran == ['longass-container-id']


    @patch('drillmaster.service_agent.time')
    def test_repeat_ping_and_timeout(self, mock_time):
        mock_time.monotonic.side_effect = [0, 0.2, 0.6, 0.8, 1]
        fake_context = FakeRunningContext()
        fake_service = FakeService(fail_ping=True)
        agent = ServiceAgent(fake_service, DEFAULT_START_OPTIONS, fake_context)
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
        options = Options(True, 'the-network', 0.01)
        agent = ServiceAgent(fake_service, options, fake_context)
        agent.start_service()
        agent.join()
        assert fake_service.ping_count > 0
        assert fake_context.started_services == []
        assert len(fake_context.failed_services) == 1
        assert fake_context.failed_services[0].name == 'service1'


    def test_call_collection_failed_on_error(self):
        fake_context = FakeRunningContext()
        fake_service = FakeService(exception_at_init=ValueError)
        agent = ServiceAgent(fake_service, DEFAULT_START_OPTIONS, fake_context)
        agent.start_service()
        agent.join()
        assert fake_service.ping_count > 0
        assert fake_context.started_services == []
        assert len(fake_context.failed_services) == 1
        assert fake_context.failed_services[0].name == 'service1'


    def test_stop_container_does_not_exist(self):
        fake_context = FakeRunningContext()
        fake_service = FakeService(exception_at_init=ValueError)
        agent = ServiceAgent(fake_service, DEFAULT_START_OPTIONS, fake_context)
        agent.stop_service()
        agent.join()
        assert agent.status == AgentStatus.STOPPED


    def test_stop_existing_container(self):
        fake_context = FakeRunningContext()
        fake_service = FakeService(exception_at_init=ValueError)
        container = FakeContainer(name='{}-drillmaster-5678'.format(fake_service.name),
                                  stopped=False,
                                  removed=False,
                                  network='the-network',
                                  status='running')
        self.docker._existing_containers = [container]
        agent = ServiceAgent(fake_service, DEFAULT_STOP_OPTIONS, fake_context)
        agent.stop_service()
        agent.join()
        assert agent.status == AgentStatus.STOPPED
        assert container.stopped
        assert len(fake_context.stopped_services) == 1
        assert fake_context.stopped_services[0] is fake_service
