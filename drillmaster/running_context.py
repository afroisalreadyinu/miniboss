from drillmaster.service_agent import (ServiceAgent,
                                       Options,
                                       StopOptions,
                                       AgentStatus)

class RunningContext:

    def __init__(self, services_by_name, collection, options: Options):
        self.service_agents = {name: ServiceAgent(service, collection, options)
                               for name, service in services_by_name.items()}
        self.without_dependencies = [x for x in self.service_agents.values() if x.can_start]
        self.waiting_agents = {name: agent for name, agent in self.service_agents.items()
                               if not agent.can_start}

    @property
    def done(self):
        return all(x.status == AgentStatus.STARTED for x in self.service_agents.values())

    def service_started(self, started_service):
        self.service_agents.pop(started_service)
        startable = []
        for name, agent in self.waiting_agents.items():
            agent.process_service_started(started_service)
            if agent.can_start:
                startable.append(name)
        return [self.waiting_agents.pop(name) for name in startable]
