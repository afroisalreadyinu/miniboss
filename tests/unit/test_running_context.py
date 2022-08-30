import unittest
from types import SimpleNamespace as Bunch
from unittest.mock import patch

from common import DEFAULT_OPTIONS, FakeService

from miniboss.running_context import RunningContext
from miniboss.service_agent import Options
from miniboss.services import connect_services


class RunningContextTests(unittest.TestCase):
    def test_service_started(self):
        services = connect_services(
            [
                FakeService(name="service1", dependencies=[]),
                FakeService(name="service2", dependencies=["service1"]),
            ]
        )
        context = RunningContext(services, DEFAULT_OPTIONS)
        assert len(context.agent_set) == 2
        context.service_started(services["service1"])
        assert len(context.processed_services) == 1
        assert context.processed_services[0].name == "service1"
        assert len(context.agent_set) == 1
        assert services["service2"] in context.agent_set
        assert context.agent_set[services["service2"]].can_start

    def test_ready_to_start_and_stop(self):
        services = connect_services(
            [
                FakeService(name="service1", dependencies=[]),
                FakeService(name="service2", dependencies=["service1"]),
            ]
        )
        context = RunningContext(services, DEFAULT_OPTIONS)
        assert len(context.ready_to_start) == 1
        assert context.ready_to_start[0].service == services["service1"]
        assert len(context.ready_to_stop) == 1
        assert context.ready_to_stop[0].service == services["service2"]

    def test_service_failed(self):
        service = FakeService(name="service1", dependencies=[])
        context = RunningContext({"service": service}, DEFAULT_OPTIONS)
        context.service_failed(service)
        assert len(context.failed_services) == 1
        assert len(context.agent_set) == 0
        assert len(context.processed_services) == 0

    def test_service_stopped(self):
        services = connect_services(
            [
                FakeService(name="service1", dependencies=[]),
                FakeService(name="service2", dependencies=["service1"]),
            ]
        )
        context = RunningContext(services, DEFAULT_OPTIONS)
        context.service_stopped(services["service2"])
        assert len(context.agent_set) == 1
        assert len(context.processed_services) == 1
        assert context.processed_services[0] is services["service2"]
        assert services["service1"] in context.agent_set
        assert context.agent_set[services["service1"]].can_stop

    def test_done_on_started(self):
        services = connect_services(
            [
                FakeService(name="service1", dependencies=[]),
                FakeService(name="service2", dependencies=[]),
            ]
        )
        context = RunningContext(services, DEFAULT_OPTIONS)
        assert not context.done
        context.service_started(services["service1"])
        assert not context.done
        context.service_started(services["service2"])
        assert context.done
        assert len(context.agent_set) == 0

    def test_done_on_fail(self):
        services = connect_services(
            [
                FakeService(name="service1", dependencies=[]),
                FakeService(name="service2", dependencies=[]),
            ]
        )
        context = RunningContext(services, DEFAULT_OPTIONS)
        assert not context.done
        context.service_started(services["service1"])
        assert not context.done
        context.service_failed(services["service2"])
        assert context.done

    def test_fail_dependencies(self):
        """If a service fails to start, all the other services that depend on it are
        also registered as failed"""
        services = connect_services(
            [
                FakeService(name="service1", dependencies=[]),
                FakeService(name="service2", dependencies=["service1"]),
            ]
        )
        context = RunningContext(services, DEFAULT_OPTIONS)
        context.service_failed(services["service1"])
        assert len(context.failed_services) == 2

    @patch("miniboss.running_context.threading")
    def test_service_started_lock_call(self, mock_threading):
        services = connect_services(
            [
                FakeService(name="service1", dependencies=[]),
                FakeService(name="service2", dependencies=["service1"]),
            ]
        )
        context = RunningContext(services, DEFAULT_OPTIONS)
        context.service_started(services["service1"])
        mock_lock = mock_threading.Lock.return_value
        assert mock_lock.__enter__.call_count == 1

    @patch("miniboss.running_context.threading")
    def test_service_failed_lock_call(self, mock_threading):
        services = connect_services(
            [
                FakeService(name="service1", dependencies=[]),
                FakeService(name="service2", dependencies=["service1"]),
            ]
        )
        context = RunningContext(services, DEFAULT_OPTIONS)
        context.service_failed(services["service1"])
        mock_lock = mock_threading.Lock.return_value
        # This has to be 2 because service1 has a dependency, and it has to be
        # locked as well
        assert mock_lock.__enter__.call_count == 2
