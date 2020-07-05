import unittest
from types import SimpleNamespace as Bunch

from drillmaster.running_context import RunningContext
from drillmaster.service_agent import Options

class FakeService:
    def __init__(self, name, dependencies):
        self.name = name
        self.dependencies = dependencies

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.name == other.name

class RunningContextTests(unittest.TestCase):

    def test_service_started(self):
        service1 = FakeService(name='service1', dependencies=[])
        service2 = FakeService(name='service2', dependencies=[service1])
        context = RunningContext({'service1': service1, 'service2': service2},
                                 Options(False, 'the-network', 50))
        assert len(context.agent_set) == 2
        context.service_started(service1)
        assert len(context.processed_services) == 1
        assert context.processed_services[0].name == 'service1'
        assert len(context.agent_set) == 1
        assert service2 in context.agent_set
        assert context.agent_set[service2].can_start

    def test_service_failed(self):
        service = FakeService(name='service1', dependencies=[])
        context = RunningContext({'service': service}, Options(False, 'the-network', 50))
        context.service_failed(service)
        assert len(context.failed_services) == 1
        assert len(context.agent_set) == 0

    def test_done_on_started(self):
        service1 = FakeService(name='service1', dependencies=[])
        service2 = FakeService(name='service2', dependencies=[])
        context = RunningContext({'service1': service1, 'service2': service2},
                                 Options(False, 'the-network', 50))
        assert not context.done
        context.service_started(service1)
        assert not context.done
        context.service_started(service2)
        assert context.done
        assert len(context.agent_set) == 0

    def test_done_on_fail(self):
        service1 = FakeService(name='service1', dependencies=[])
        service2 = FakeService(name='service2', dependencies=[])
        context = RunningContext({'service1': service1, 'service2': service2},
                                 Options(False, 'the-network', 50))
        assert not context.done
        context.service_started(service1)
        assert not context.done
        context.service_failed(service2)
        assert context.done

    def test_fail_dependencies(self):
        """If a service fails to start, all the other services that depend on it are
        also registered as failed"""
        service1 = FakeService(name='service1', dependencies=[])
        service2 = FakeService(name='service2', dependencies=[service1])
        context = RunningContext({'service1': service1, 'service2': service2},
                                 Options(False, 'the-network', 50))
        context.service_failed(service1)
        assert len(context.failed_services) == 2
