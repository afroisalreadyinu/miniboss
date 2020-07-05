import unittest
from types import SimpleNamespace as Bunch

from drillmaster.running_context import RunningContext
from drillmaster.service_agent import Options

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
