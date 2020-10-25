class MinibossException(Exception):
    pass

class ServiceLoadError(MinibossException):
    pass

class ServiceDefinitionError(MinibossException):
    pass

class ServiceAgentException(MinibossException):
    pass

class MinibossCLIError(MinibossException):
    pass

class ContextError(MinibossException):
    pass

class DockerException(MinibossException):
    pass

class ContainerStartException(DockerException):
    def __init__(self, logs, container_name, *args, **kwargs):
        self.logs = logs
        self.container_name = container_name
        super().__init__(*args, **kwargs)

    def __str__(self):
        return "Logs: \n" + self.logs
