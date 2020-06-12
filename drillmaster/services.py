import random
import socket
import time
import logging
from collections import Counter, Mapping
import threading
import copy

import click
import requests
import furl
import requests.exceptions

import docker

DIGITS = "0123456789"

logging.basicConfig(
    level=logging.INFO,
    style='{',
    format= '[%(asctime)s] %(pathname)s:%(lineno)d %s(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

KEYCLOAK_PORT = 8090
OSTKREUZ_PORT = 8080

the_docker = None

class KeycloakException(Exception):
    def __init__(self, msg, *args, **kwargs):
        super().__init__(msg.format(*args, **kwargs))

class TestingException(Exception):
    def __init__(self, msg, *args, **kwargs):
        super().__init__(msg.format(*args, **kwargs))


class Keycloak:

    def __init__(self, host: furl.furl):
        self.host = host
        self.token = None

    def post(self, path, *args, expect_200=True, content_type='application/json', **kwargs):
        kwargs.setdefault('headers', {})
        kwargs['headers']["Accept"] = "application/json"
        kwargs['headers']["Content-Type"] = content_type
        if self.token:
            kwargs['headers']["Authorization"] = "Bearer {}".format(self.token)
        try:
            response = requests.post(self.host / path, *args, **kwargs)
        except requests.exceptions.ConnectionError:
            raise KeycloakException("Could not reach Keycloak host at {!s}", self.host) from None
        if expect_200 and response.status_code > 299:
            raise KeycloakException("Keycloak error, status code {:d}, reason: {:s}",
                                    response.status_code, response.text)
        return response


    def put(self, path, *args, **kwargs):
        kwargs.setdefault('headers', {})
        kwargs['headers']["Accept"] = "application/json"
        kwargs['headers']["Content-Type"] = 'application/json'
        kwargs['headers']["Authorization"] = "Bearer {}".format(self.token)
        try:
            response = requests.put(self.host / path, *args, **kwargs)
        except requests.exceptions.ConnectionError:
            raise KeycloakException("Could not reach Keycloak host at {!s}", self.host) from None
        return response


    def get(self, path, *args, expect_200=True, **kwargs):
        try:
            response = requests.get(
                self.host / path, *args,
                headers={"Accept": "application/json",
                         "Authorization": "Bearer {}".format(self.token)},
                **kwargs)
        except requests.exceptions.ConnectionError:
            raise KeycloakException("Could not reach Keycloak host at {!s}", self.host) from None
        if expect_200 and response.status_code > 299:
            raise KeycloakException("Keycloak error, status code {:d}, reason: {:s}",
                                    response.status_code, response.text)
        return response.json()

    def ping(self, timeout):
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            try:
                requests.get(self.host)
            except requests.exceptions.ConnectionError:
                continue
            else:
                return True
        return False

    def fetch_auth_token(self):
        response = self.post("auth/realms/master/protocol/openid-connect/token",
                             content_type="application/x-www-form-urlencoded",
                             data={"username": "admin",
                                   'password': 'admin',
                                   'grant_type': 'password',
                                   'client_id': 'admin-cli'})
        self.token = response.json()['access_token']


    def get_realms(self):
        realms = self.get('auth/admin/realms')
        return {x['realm']: x for x in realms}

    def get_clients(self, realm):
        path = "auth/admin/realms/{}/clients".format(realm)
        return {x['clientId']: x for x in self.get(path)}

    def create_realm(self, realm_name):
        realms = self.get_realms()
        if realm_name in realms:
            return realms[realm_name]
        response = self.post('auth/admin/realms',
                             json={'realm': realm_name, 'enabled': True, 'sslRequired': 'none'})

    def create_client(self, realm, client_id):
        clients = self.get_clients(realm)
        if client_id in clients:
            client = clients[client_id]
        else:
            path = "auth/admin/realms/{}/clients".format(realm)
            response = self.post(path, json={'clientId': 'ostkreuz-backend',
                                             'redirectUris': ["http://localhost:8080/*"],
                                             'publicClient': False})
            client = self.get_clients(realm)[client_id]
        secret = self.get("auth/admin/realms/{}/clients/{}/client-secret".format(realm, client['id']))
        client['secret'] = secret
        return client

    def add_user(self, realm, username, email):
        path = "auth/admin/realms/{}/users".format(realm)
        users = self.get(path)
        if email not in [x['email'] for x in users]:
            self.post(path.format(realm),
                      json={"email": email, "username": username, 'enabled': True})
            users = self.get(path)
        user = [u for u in users if u['email'] == email][0]
        credentials_path = "auth/admin/realms/{}/users/{}/credentials".format(realm, user['id'])
        credentials = self.get(credentials_path)
        if len(credentials) != 0:
            return
        password_path = "auth/admin/realms/{}/users/{}/reset-password".format(realm, user['id'])
        response = self.put(password_path,
                            json={'type': 'password', 'value': 'ostkreuz', 'temporary': False})


    def create_test_data(self):
        if not self.ping(timeout=60):
            raise TestingException("Could not start keycloak container, please look at logs")
        self.fetch_auth_token()
        self.create_realm('ostkreuz')
        client = self.create_client('ostkreuz', 'ostkreuz-backend')
        self.add_user("ostkreuz", "ulas", "ulas@ostkreuz.com")
        return client['id'], client['secret']['value']


class ServiceLoadError(Exception):
    pass

class ServiceDefinitionError(Exception):
    pass

class ServiceMeta(type):
    def __new__(cls, name, bases, attrdict):
        if not bases:
            return super().__new__(cls, name, bases, attrdict)
        if not isinstance(attrdict.get("name"), str) or attrdict["name"] == "":
            raise ServiceDefinitionError(
                "Field 'name' of service class {:s} must be a non-empty string".format(name))
        if not isinstance(attrdict.get("image"), str) or attrdict["image"] == "":
            raise ServiceDefinitionError(
                "Field 'image' of service class {:s} must be a non-empty string".format(name))
        if "ports" in attrdict and not isinstance(attrdict["ports"], Mapping):
            raise ServiceDefinitionError(
                "Field 'ports' of service class {:s} must be a mapping".format(name))
        if "env" in attrdict and not isinstance(attrdict["env"], Mapping):
            raise ServiceDefinitionError(
                "Field 'env' of service class {:s} must be a mapping".format(name))
        return super().__new__(cls, name, bases, attrdict)


class Service(metaclass=ServiceMeta):
    name = None
    dependencies = []
    ports = {}
    env = {}

    def ping(self):
        pass

class ServiceAgent:

    def __init__(self, service: Service):
        self.service = service
        self.open_dependencies = [x.name for x in service.dependencies]

    @property
    def can_start(self):
        return self.open_dependencies == []

    def process_service_started(self, service_name):
        if service_name in self.open_dependencies:
            self.open_dependencies.remove(service_name)


class ServiceCollection:

    def __init__(self):
        self.all_by_name = {}
        self._base_class = Service

    def load_definitions(self):
        services = self._base_class.__subclasses__()
        name_counter = Counter()
        for service in services:
            self.all_by_name[service.name] = service
            name_counter[service.name] += 1
        multiples = [name for name,count in name_counter.items() if count > 1]
        if multiples:
            raise ServiceLoadError("Repeated service names: {:s}".format(",".join(multiples)))
        for service in self.all_by_name.values():
            dependencies = service.dependencies[:]
            service.dependencies = [self.all_by_name[dependency] for dependency in dependencies]
        self.check_circular_dependencies()

    def check_circular_dependencies(self):
        with_dependencies = [x for x in self.all_by_name.values() if x.dependencies != []]
        for service in with_dependencies:
            start = service.name
            count = 0
            def go_up_dependencies(checked):
                nonlocal count
                count += 1
                for dependency in checked.dependencies:
                    if dependency.name == start:
                        raise ServiceLoadError("Circular dependency detected")
                    if count == len(self.all_by_name):
                        return
                    go_up_dependencies(dependency)
            go_up_dependencies(service)

    def __len__(self):
        return len(self.all_by_name)

    def start_all(self, network_name):
        service_agents = {name: ServiceAgent(service) for name, service in self.all_by_name.items()}
        while service_agents:
            without_dependencies = [x for x in service_agents.values() if x.can_start]
            waiting_agents = [x for x in service_agents.values() if not x.can_start]
            threads = []
            for agent in without_dependencies:
                self.run_image(agent.service, network_name)
                def wait_and_remove():
                    agent.service.ping(50)
                    service_agents.pop(agent.service.name)
                    for waiting in waiting_agents:
                        waiting.process_service_started(agent.service.name)
                ping_thread = threading.Thread(target=wait_and_remove)
                ping_thread.start()
                threads.append(ping_thread)
            for thread in threads:
                thread.join()

    def run_image(self, service: Service, network_name):
        global the_docker
        container_name = "{:s}-drillmaster-{:s}".format(service.name, ''.join(random.sample(DIGITS, 4)))
        networking_config = the_docker.api.create_networking_config({
            network_name: the_docker.api.create_endpoint_config(aliases=[service.name])
        })
        host_config=the_docker.api.create_host_config(port_bindings=service.ports)
        container = the_docker.api.create_container(
            service.image,
            detach=True,
            name=container_name,
            ports=list(service.ports.keys()),
            environment=service.env,
            host_config=host_config,
            networking_config=networking_config)
        the_docker.api.start(container.get('Id'))
        return container


def start_services(use_existing, exclude, network_name):
    global the_docker
    the_docker = docker.from_env()
    collection = ServiceCollection()
    collection.load_definitions()
    existing_network = the_docker.networks.list(names=[network_name])
    if not existing_network:
        network = the_docker.networks.create(network_name, driver="bridge")
        logger.info("Created network %s", network_name)
    service_names = collection.start_all(network_name)
    logger.info("Started services: %s", ",".join(service_names))
