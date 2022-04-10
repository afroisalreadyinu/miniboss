from __future__ import annotations
import threading
from typing import TYPE_CHECKING

from miniboss.service_agent import (ServiceAgent,
                                    Options)
if TYPE_CHECKING:
    from miniboss.services import Service

class RunningContext:

    def __init__(self, services_by_name: dict[str, Service], options: Options):
        super().__init__()
        self.agent_set = {service: ServiceAgent(service, options, self)
                          for name, service in services_by_name.items()}
        self.failed_services: list[Service] = []
        self.processed_services: list[Service] = []
        self.service_pop_lock = threading.Lock()

    @property
    def done(self) -> bool:
        return self.agent_set == {}

    @property
    def context_failed(self)-> bool:
        return bool(self.failed_services)

    @property
    def ready_to_start(self) -> list[ServiceAgent]:
        return [x for x in self.agent_set.values() if x.can_start]

    @property
    def ready_to_stop(self) -> list[ServiceAgent]:
        return [x for x in self.agent_set.values() if x.can_stop]

    def service_failed(self, failed_service: Service) -> None:
        with self.service_pop_lock:
            self.agent_set.pop(failed_service)
            self.failed_services.append(failed_service)
        services_left = list(self.agent_set.keys())
        for service in services_left:
            if failed_service in service.dependencies:
                self.service_failed(service)

    def service_started(self, started_service: Service) -> None:
        with self.service_pop_lock:
            self.agent_set.pop(started_service)
            self.processed_services.append(started_service)
            for agent in self.agent_set.values():
                agent.process_service_started(started_service)


    def service_stopped(self, stopped_service: Service) -> None:
        with self.service_pop_lock:
            self.agent_set.pop(stopped_service)
            self.processed_services.append(stopped_service)
            for agent in self.agent_set.values():
                agent.process_service_stopped(stopped_service)
