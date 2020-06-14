import docker

_the_docker = None

def get_client():
    global _the_docker
    if _the_docker is not None:
        _the_docker = docker.from_env()
    return _the_docker
