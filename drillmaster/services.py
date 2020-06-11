import random
import socket
import time
import logging
from collections import Counter

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

Services = None

def check_circular_dependencies():
    with_dependencies = [x for x in Services.values() if x.dependencies != []]
    for service in with_dependencies:
        start = service.name
        count = 0
        def go_up_dependencies(checked):
            nonlocal count
            count += 1
            for dependency in checked.dependencies:
                if dependency.name == start:
                    raise ServiceLoadError("Circular dependency detected")
                if count == len(Services):
                    return
                go_up_dependencies(dependency)
        go_up_dependencies(service)


# TODO: Turn this into a data class
class Service:
    dependencies = []

    @classmethod
    def load_definitions(cls):
        global Services
        services = cls.__subclasses__()
        name_counter = Counter()
        for service in services:
            name_counter[service.name] += 1
        multiples = [name for name,count in name_counter.items() if count > 1]
        if multiples:
            raise ServiceLoadError("Repeated service names: {:s}".format(",".join(multiples)))
        Services = {service.name: service for service in services}
        for service in Services.values():
            dependencies = service.dependencies[:]
            service.dependencies = [Services[dependency] for dependency in dependencies]
        check_circular_dependencies()

    def ping(self):
        pass


def run_image(service: Service, network_name):
    container_name = "{:s}-drillmaster-{:s}".format(service.name, ''.join(random.sample(DIGITS, 4)))
    networking_config = the_docker.api.create_networking_config({
        network_name: the_docker.api.create_endpoint_config(aliases=[services.name])
    })
    host_config=the_docker.api.create_host_config(port_bindings=ports)
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
    Service.load_definitions()
    existing_network = the_docker.networks.list(names=[network_name])
    if not existing_network:
        network = the_docker.networks.create(network_name, driver="bridge")
        logger.info("Created network %s", network_name)
    all_services = Services.values()
    while all_services:
        without_dependencies = [x for x in all_services if x.dependencies == []]
        threads = []
        for service in without_dependencies:
            run_image(service, network_name)
            def wait_and_remove():
                service.ping()
                all_services.remove(service.name)
            ping_thread = threading.Thread(target=wait_and_remove)
            ping_thread.start()
            threads.append(ping_thread)
        for thread in threads:
            thread.join()
    return
    containers = start_keycloak()
    try:
        keycloak = Keycloak(furl.furl("http://localhost:{:d}".format(KEYCLOAK_PORT)))
        logger.info("Creating test data on keycloak")
        client_id, client_secret = keycloak.create_test_data()
        containers['ostkreuz'] = add_ostkreuz(client_secret)
    except:
        logger.exception("Failed to run")
        import pdb;pdb.set_trace()
    else:

        import pdb;pdb.set_trace()
