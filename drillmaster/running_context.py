import threading

from drillmaster.service_agent import (ServiceAgent,
                                       Options,
                                       StopOptions,
                                       AgentStatus)

class RunningContext:

    def __init__(self, services_by_name, options: Options):
        super().__init__()
        self.agent_set = {service: ServiceAgent(service, options, self)
                          for name, service in services_by_name.items()}
        self.failed_services = []
        self.processed_services = []
        self.service_pop_lock = threading.Lock()

    @property
    def done(self):
        return self.agent_set == {}

    @property
    def context_failed(self):
        return self.failed_services != []

    @property
    def ready_to_start(self):
        return [x for x in self.agent_set.values() if x.can_start]

    def service_failed(self, failed_service):
        with self.service_pop_lock:
            self.agent_set.pop(failed_service)
            self.failed_services.append(failed_service)
        services_left = list(self.agent_set.keys())
        for service in services_left:
            if failed_service in service.dependencies:
                self.service_failed(service)

    def service_started(self, started_service):
        with self.service_pop_lock:
            started = self.agent_set.pop(started_service)
            self.processed_services.append(started_service)
            for agent in self.agent_set.values():
                agent.process_service_started(started_service)
