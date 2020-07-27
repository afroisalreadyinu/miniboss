class MinibossException(Exception):
    pass

class ServiceLoadError(MinibossException):
    pass

class ServiceDefinitionError(MinibossException):
    pass

class ServiceAgentException(MinibossException):
    pass

class DockerException(MinibossException):
    pass

class MinibossCLIError(MinibossException):
    pass

class ContextError(MinibossException):
    pass
