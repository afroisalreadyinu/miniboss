import unittest
from unittest.mock import patch
from types import SimpleNamespace as Bunch

from drillmaster import service_agent, context
from drillmaster.service_agent import ServiceAgent, Options

from common import MockDocker

DEFAULT_OPTIONS = Options(False, 'the-network', 1)

class FakeServiceCollection:
    def __init__(self):
        self.started_service = None
        self.failed_service = None

    def start_next(self, started_service):
        self.started_service = started_service

    def service_failed(self, failed_service):
        self.failed_service = failed_service

class FakeService:
    name = 'service1'
    image = 'not/used'
    dependencies = []
    ports = {}
    env = {}
    always_start_new = False

    def __init__(self, fail_ping=False, exception_at_init=None):
        self.fail_ping = fail_ping
        self.exception_at_init = exception_at_init
        self.ping_count = 0
        self.init_called = False

    def ping(self):
        self.ping_count += 1
        return not self.fail_ping

    def post_start_init(self):
        self.init_called = True
        if self.exception_at_init:
            raise self.exception_at_init()
        return True

class ServiceAgentTests(unittest.TestCase):

    def setUp(self):
        self.docker = MockDocker()
        def get_fake_client():
            return self.docker
        service_agent.get_client = get_fake_client


    def test_can_start(self):
        service1 = Bunch(name='service1', dependencies=[])
        service2 = Bunch(name='service2', dependencies=[service1])
        agent = ServiceAgent(service2, None, DEFAULT_OPTIONS)
        assert agent.can_start is False

    def test_run_image(self):
        agent = ServiceAgent(FakeService(), None, DEFAULT_OPTIONS)
        agent.run_image()
        assert len(self.docker._containers_created) == 1
        assert len(self.docker._containers_started) == 1


    def test_run_image_extrapolate_env(self):
        service = FakeService()
        service.env = {'ENV_ONE': 'http://{host}:{port:d}'}
        context.Context['host'] = 'zombo.com'
        context.Context['port'] = 80
        agent = ServiceAgent(service, None, DEFAULT_OPTIONS)
        agent.run_image()
        assert len(self.docker._containers_started) == 1
        container = list(self.docker._containers_created.values())[0]
        assert container['environment']['ENV_ONE'] == 'http://zombo.com:80'


    def test_agent_status_change_happy_path(self):
        class ServiceAgentTestSubclass(ServiceAgent):
            def ping(self):
                assert self.status == 'in-progress'
                return super().ping()
        agent = ServiceAgentTestSubclass(FakeService(), FakeServiceCollection(), DEFAULT_OPTIONS)
        assert agent.status == 'null'
        agent.run()
        assert agent.status == 'started'


    def test_agent_status_change_sad_path(self):
        class ServiceAgentTestSubclass(ServiceAgent):
            def ping(self):
                assert self.status == 'in-progress'
                raise ValueError("I failed miserably")
        agent = ServiceAgentTestSubclass(FakeService(), FakeServiceCollection(), DEFAULT_OPTIONS)
        assert agent.status == 'null'
        agent.run()
        assert agent.status == 'failed'


    def test_skip_if_running_on_same_network(self):
        agent = ServiceAgent(FakeService(), None, DEFAULT_OPTIONS)
        self.docker._existing_containers = [Bunch(status='running')]
        agent.run_image()
        assert len(self.docker._containers_created) == 0
        assert len(self.docker._containers_started) == 0


    def test_start_old_container_if_exists(self):
        agent = ServiceAgent(FakeService(), None, DEFAULT_OPTIONS)
        restarted = False
        def start():
            nonlocal restarted
            restarted = True
        self.docker._existing_containers = [Bunch(status='exited', start=start)]
        agent.run_image()
        assert len(self.docker._containers_created) == 0
        assert len(self.docker._containers_started) == 0
        assert restarted


    def test_start_new_if_run_new_containers(self):
        agent = ServiceAgent(FakeService(), None, Options(True, 'the-network', 1))
        restarted = False
        def start():
            nonlocal restarted
            restarted = True
        self.docker._existing_containers = [Bunch(status='exited', start=start)]
        agent.run_image()
        assert len(self.docker._containers_created) == 1
        assert len(self.docker._containers_started) == 1
        assert not restarted


    def test_start_new_if_always_strat_new(self):
        service = FakeService()
        service.always_start_new = True
        agent = ServiceAgent(service, None, Options(True, 'the-network', 1))
        restarted = False
        def start():
            nonlocal restarted
            restarted = True
        self.docker._existing_containers = [Bunch(status='exited', start=start)]
        agent.run_image()
        assert len(self.docker._containers_created) == 1
        assert len(self.docker._containers_started) == 1
        assert not restarted


    def test_ping_and_init_after_run(self):
        fake_collection = FakeServiceCollection()
        fake_service = FakeService()
        agent = ServiceAgent(fake_service, fake_collection, DEFAULT_OPTIONS)
        agent.run()
        assert fake_collection.started_service == 'service1'
        assert fake_service.ping_count == 1
        assert fake_service.init_called


    @patch('drillmaster.service_agent.time')
    def test_ping_timeout(self, mock_time):
        mock_time.monotonic.side_effect = [0, 0.2, 0.6, 0.8, 1]
        fake_collection = FakeServiceCollection()
        fake_service = FakeService(fail_ping=True)
        agent = ServiceAgent(fake_service, fake_collection, DEFAULT_OPTIONS)
        agent.run()
        assert fake_service.ping_count == 3
        assert mock_time.sleep.call_count == 3


    def test_service_failed_on_failed_ping(self):
        fake_collection = FakeServiceCollection()
        fake_service = FakeService(fail_ping=True)
        agent = ServiceAgent(fake_service, fake_collection, DEFAULT_OPTIONS)
        agent.run()
        assert fake_service.ping_count > 0
        assert fake_collection.started_service is None
        assert fake_collection.failed_service == 'service1'


    def test_call_collection_failed_on_error(self):
        fake_collection = FakeServiceCollection()
        fake_service = FakeService(exception_at_init=ValueError)
        agent = ServiceAgent(fake_service, fake_collection, DEFAULT_OPTIONS)
        agent.run()
        assert fake_service.ping_count > 0
        assert fake_collection.started_service is None
        assert fake_collection.failed_service == 'service1'
