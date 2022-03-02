[![afroisalreadyinu](https://circleci.com/gh/afroisalreadyinu/miniboss.svg?style=svg)](https://app.circleci.com/pipelines/github/afroisalreadyinu/miniboss)

[![PyPI version](https://badge.fury.io/py/miniboss.svg)](https://badge.fury.io/py/miniboss)

<img src="https://github.com/afroisalreadyinu/miniboss/raw/main/logo.png" width="200">

# miniboss

miniboss is a Python application for locally running a collection of
interdependent docker services, individually rebuilding and restarting them, and
managing application state with lifecycle hooks. Services definitions can be
written in Python, allowing the use of programming logic instead of markup.

## Why not docker-compose?

First and foremost, good old Python instead of YAML. `docker-compose` is in the
school of yaml-as-service-description, which means that going beyond a static
description of a service set necessitates templates, or some kind of scripting.
One could just as well use a full-blown programming language, while trying to
keep simple things simple. Another thing sorely missing in `docker-compose` is
lifecycle hooks, i.e. a mechanism whereby scripts can be executed when the state
of a container changes. Lifecycle hooks have been
[requested](https://github.com/docker/compose/issues/1809)
[multiple](https://github.com/docker/compose/issues/5764)
[times](https://github.com/compose-spec/compose-spec/issues/84), but were not
deemed to be in the domain of `docker-compose`.

## Usage

Here is a very simple service specification:

```python
#! /usr/bin/env python3
import miniboss

miniboss.group_name('readme-demo')

class Database(miniboss.Service):
    name = "appdb"
    image = "postgres:10.6"
    env = {"POSTGRES_PASSWORD": "dbpwd",
           "POSTGRES_USER": "dbuser",
           "POSTGRES_DB": "appdb" }
    ports = {5432: 5433}

class Application(miniboss.Service):
    name = "python-todo"
    image = "afroisalreadyin/python-todo:0.0.1"
    env = {"DB_URI": "postgresql://dbuser:dbpwd@appdb:5432/appdb"}
    dependencies = ["appdb"]
    ports = {8080: 8080}
    stop_signal = "SIGINT"

if __name__ == "__main__":
    miniboss.cli()
```

The first use of miniboss is in the call to `miniboss.group_name`, which
specifies a name for this group of services. If you don't set it, sluggified
form of the directory name will be used. Group name is used to identify the
services and the network defined in a miniboss file. Setting it manually to a
non-default value will allow miniboss to manage multiple collections in the same
directory.

A **service** is defined by subclassing `miniboss.Service` and overriding, in
the minimal case, the fields `image` and `name`. The `env` field specifies the
environment variables. As in the case of the `appdb` service, you can use
ordinary variables anywhere Python accepts them. The other available fields are
explained in the section [Service definition
fields](#service-definition-fields). In the [above example](#usage), we are
creating two services: The application service `python-todo` (a simple Flask
todo application defined in the `sample-apps` directory) depends on `appdb` (a
Postgresql container), specified through the `dependencies` field. As in
`docker-compose`, this means that `python-todo` will get started after `appdb`
reaches running status.

The `miniboss.cli` function is the main entry point; you need to call it in the
main section of your script. Let's run the script above without arguments, which
leads to the following output:

```
Usage: miniboss-main.py [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  start
  stop
```

We can start our small collection of services by running `./miniboss-main.py
start`. After spitting out some logging text, you will see that starting the
containers failed, with the `python-todo` service throwing an error that it
cannot reach the database. The reason for this error is that the Postgresql
process has started, but is still initializing, and does not accept connections
yet. The standard way of dealing with this issue is to include backoff code in
your application that checks on the database port regularly, until the
connection is accepted. `miniboss` offers an alternative with [lifecycle
events](#lifecycle-events). For the time being, you can simply rerun
`./miniboss-main.py start`, which will restart only the `python-todo` service,
as the other one is already running. You should be able to navigate to
`http://localhost:8080` and view the todo app page.

You can also exclude services from the list of services to be started with the
`--exclude` argument; `./miniboss-main.py start --exclude python-todo` will
start only `appdb`. If you exclude a service that is depended on by another, you
will get an error. If a service fails to start (i.e. container cannot be started
or the lifecycle events fail), it and all the other services that depend on it
are registered as failed.

### Stopping services

Once you are done working with a collection, you can stop the running services
with `miniboss-main.py stop`. This will stop the services in the reverse order
of dependency, i.e. first `python-todo` and then `appdb`. Exclusion is possible
also when stopping services with the same `--exclude` argument. Running
`./miniboss-main.py stop --exclude appdb` will stop only the `python-todo`
service. If you exclude a service whose dependency will be stopped, you will get
an error. If, in addition to stopping the service containers, you want to remove
them, include the option `--remove`. If you don't remove the containers,
miniboss will restart the existing containers (modulo changes in service
definition) instead of creating new ones the next time it's called with `start`.
This behavior can be modified with the `always_start_new` field; see the details
in [Service definition fields](#service-definition-fields).

### Reloading a service

miniboss also allows you to reload a specific service by building a new
container image from a directory. You need to provide the path to the directory
in which the Dockerfile and build context of a service resides in order to use
this feature. You can also provide an alternative Dockerfile name. Here is an
example:

```python
class Application(miniboss.Service):
    name = "python-todo"
    image = "afroisalreadyin/python-todo:0.0.1"
    env = {"DB_URI": "postgresql://dbuser:dbpwd@appdb:5432/appdb"}
    dependencies = ["appdb"]
    ports = {8080: 8080}
    build_from = "python-todo/"
    dockerfile = "Dockerfile"
```

The `build_from` option has to be a path relative to the main miniboss file.
With such a service configuration, you can run `./miniboss-main.py reload
python-todo`, which will cause miniboss to build the container image, stop the
running service container, and restart the new image. Since [the
context](#the-global-context) generated at start is saved in a file, any context
values used in the service definition are available to the new container.

## Lifecycle events

One of the differentiating feature of miniboss is lifecycle events, which are
hooks that can be customized to execute code at certain points in a service's or
the whole collection's lifecycle.

### Per-service events

For per-service events, `miniboss.Service` has three methods that can be
overriden in order to correctly change states and execute actions on the
container:

- **`Service.pre_start()`**: Executed before the service is started. Can be used
  for things like initializing mount directory contents or downloading online
  content.

- **`Service.ping()`**: Executed repeatedly right after the service starts with
  a 0.1 second delay between executions. If this method does not return `True`
  within a given timeout value (can be set with the `--timeout` argument,
  default is 300 seconds), the service is registered as failed. Any exceptions
  in this method will be propagated, and also cause the service to fail. If
  there is already a service instance running, it is not pinged.

- **`Service.post_start()`**: This method is executed after a successful `ping`.
  It can be used to prime a service by e.g. creating data on it, or bringing it
  to a certain state. You can also use the global context in this method; see
  [The global context](#the-global-context) for details. If there is already a
  service running, or an existing container image is started insted of creating
  a new one, this method is not called.

These methods are [noop](https://en.wikipedia.org/wiki/NOP_(code)) by default. A
service is not registered as properly started before lifecycle methods are
executed successfully; only then are the dependant services started.

The `ping` method is particularly useful if you want to avoid the situation
described above, where a container starts, but the main process has not
completed initializing before any dependent services start. Here is an example
for how one would ping the `appdb` service to make sure the Postgresql database
is accepting connections:

```python
import psycopg2

class Database(miniboss.Service):
    # fields same as above

    def ping(self):
        try:
            connection = psycopg2.connect("postgresql://dbuser:dbpwd@localhost:5433/appdb")
            cur = connection.cursor()
            cur.execute('SELECT 1')
        except psycopg2.OperationalError:
            return False
        else:
            return True
```

One thing to pay attention to is that, in the call to `psycopg2.connect`, we are
using `localhost:5433` as host and port, whereas the `python-todo` environment
variable `DBURI` has `appdb:5433` instead. This is because the `ping` method is
executed on the host computer. The next section explains the details.

### Collection events

It is possible to hook into collection change commands using the following
hooks. You can call them on the base `miniboss` module and set a hook by passing
it in as the sole argument, e.g. as follows:

```python
import miniboss

def print_services(service_list):
    print("Started ", ' '.join(service_list))

miniboss.on_start_services(print_services)
```

- **`on_start_services`** hook is called after the `miniboss.start` command is
  executed. The single argument is a list of the names of the services that were
  successfully started.

- **`on_stop_services`** hook is called after the `miniboss.stop` command is
  executed. The single argument is a list of the services that were stopped.

- **`on_reload_service`** hook is called after the `miniboss.reload` command is
  executed. The single argument is the name of the service that was reloaded.


## Ports and hosts

miniboss starts services on an isolated bridge network, mapping no ports by
default. The name of this service can be specified with the `--network-name`
argument when starting a group. If it's not specified, the name will be
generated from the group name by prefixing it with `miniboss-`. On the
collection network, services can be contacted under the service name as
hostname, on the ports they are listening on. The `appdb` Postgresql service
[above](#usage), for example, can be contacted on the port 5432, the default
port on which Postgresql listens. This is the reason the host part of the
`DB_URI` environment variable on the `python-todo` service is `appdb:5432`. If
you want to reach `appdb` on the port `5433` from the host system, which would
be necessary to implement the `ping` method as above, you need to make this
mapping explicit with the `ports` field of the service definition. This field
accepts a dictionary of integer keys and values. The key is the service
container port, and the value is the host port. In the case of `appdb`, the
Postgresql port of the container is mapped to port 5433 on the local machine, in
order not to collide with any local Postgresql instances. With this
configuration, the `appdb` database can be accessed at `localhost:5433`.

### The global context

The object `miniboss.Context`, derived from the standard dict class, can be used
to store values that are accessible to other service definitions, especially in
the `env` field. For example, if you create a user in the `post_start` method of
a service, and would like to make the ID of this user available to a dependant
service, you can set it on the context with `Context['user_id'] = user.id`. In
the definition of the second service, you can refer to this value in a field
with the standard Python keyword formatting syntax, as in the following:

```python
class DependantService(miniboss.Service):
    # other fields
	env = {'USER_ID': '{user_id}'}
```

You can of course also programmatically access it as `Context['user_id']` once a
value has been set.

When a service collection is started, the generated context is saved in the file
`.miniboss-context`, in order to be used when the same containers are restarted
or a specific service is [reloaded](#reloading-a-service).

## Service definition fields

- **`name`**: The name of the service. Must be non-empty and unique for one
  miniboss definition module. The container can be contacted on the network
  under this name; it must therefore be a valid hostname.

- **`image`**: Container image of the service. Must be non-empty. You can use a
  repository URL here; if the image is not locally available, it will be pulled.
  You are highly advised to specify a tag, even if it's `latest`, because
  otherwise miniboss will not be able to identify which container image was used
  for a service, and start a new container each time. If the tag of the `image`
  is `latest`, and the `build_from` directory option is specified, the container
  image will be built each time the service is started.

- **`dependencies`**: A list of the dependencies of a service by name. If there
  are any invalid or circular dependencies, an exception will be raised.

- **`env`**: Environment variables to be injected into the service container, as
  a dict. The values of this dict can contain extrapolations from the global
  context; these extrapolations are executed when the service starts.

- **`ports`**: A mapping of the ports that must be exposed on the running host.
  Keys are ports local to the container, values are the ports of the running
  host. See [Ports and hosts](#ports-and-hosts) for more details on networking.

- **`volumes`**: Directories to be mounted inside the services as a volume, on
  which mount points. The value of `volumes` can be either a list of strings, in
  the format `"directory:mount_point:mode"`, or in the dictionary format
  `{directory: {"bind": mount_point, "mode": mode}}`. In both cases, `mode` is
  optional. See the [Using
  volumes](https://docker-py.readthedocs.io/en/stable/api.html#docker.api.container.ContainerApiMixin.create_container)
  section of Docker Python SDK documentation for details.

- **`always_start_new`**: Whether to create a new container each time a service
  is started or restart an existing but stopped container. Default value is
  `False`, meaning that by default existing container will be restarted.

- **`stop_signal`**: Which stop signal Docker should use to stop the container,
  by name (not by integer value, so don't use values from the `signal` standard
  library module here). Default is `SIGTERM`. Accepted values are `SIGINT`,
  `SIGTERM`, `SIGKILL` and `SIGQUIT`.

- **`build_from`**: The directory from which a service can be reloaded. It
  should be either absolute, or relative to the main script. Required if you
  want to be able to reload a service. If this option is specified, and the tag
  of the `image` option is `latest`, the container image will be built each time
  the service is started.

- **`dockerfile`**: Dockerfile to use when building a service from the
  `build_from` directory. Default is `Dockerfile`.

## Release notes

### 0.3.0

- Linting
- Pull container image if it doesn't exist
- Integration tests
- Mounting volumes
- Pre-start lifetime event

### 0.4.0

- Don't fail on start if excluded services depend on each other
- Destroy service if it cannot be started
- Log when custom post_start is done
- Don't start new if int-string env keys don't differ
- Don't run pre-start if container found
- Multiple clusters on single host with group id
- Build container if tag doesn't exist and it has `build_from`
- Better pypi readme with release notes

### 0.4.1

- Tests for CLI commands
- Collection lifecycle hooks

### 0.4.2

- Removed group name requirement
- Logging fixes
- Sample app fixes

## Todos

- [ ] Making easier to test on the cloud??
- [ ] Add stop-only command
- [ ] Add start-only command
- [ ] Type hints
- [ ] Run tests in container (how?)
- [ ] Exporting environment values for use in shell
- [ ] Running one-off containers
- [ ] Configuration object extrapolation
- [ ] Read specs from docker-compose.yml
- [ ] Running tests once system started
- [ ] Using context values in tests
- [ ] Dependent test suites and setups
