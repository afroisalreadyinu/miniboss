[![afroisalreadyinu](https://circleci.com/gh/afroisalreadyinu/miniboss.svg?style=svg)](https://app.circleci.com/pipelines/github/afroisalreadyinu/miniboss)

[![PyPI version](https://badge.fury.io/py/miniboss.svg)](https://badge.fury.io/py/miniboss)

# miniboss

miniboss is a Python application for locally running multiple dependent docker
services, individually rebuilding and restarting them, and managing application
state with lifecycle hooks. Services definitions can be written in Python,
allowing the use of programming logic instead of markup.

## Why not docker-compose?

First and foremost, good old Python instead of YAML. `docker-compose` is in the
school of yaml-as-service-description, which means that going beyond a static
description of a service set necessitates templates, or some kind of scripting.
One could as well use a full-blown programming language, while trying to keep
simple things simple. Another thing sorely missing in `docker-compose` is
lifecycle hooks, i.e. a mechanism whereby scripts can be executed when the state
of a container changes. Lifecycle hooks have been
[requested](https://github.com/docker/compose/issues/1809)
[multiple](https://github.com/docker/compose/issues/5764)
[times](https://github.com/compose-spec/compose-spec/issues/84), but were not
deemed to be in the domain of `docker-compose`.

The intention is to develop this package to a full-blown distributed testing
framework, which will probably take some time.

## Usage

Here is a very simple service specification:

```python
#! /usr/bin/env python3
import miniboss

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

A **service** is defined by subclassing `miniboss.Service` and overriding, in
the minimal case, the fields `image` and `name`. The `env` field specifies the
enviornment variables; as in the case of the `appdb` service, you can use
ordinary variables in this and any other value. The other available fields are
explained in the section [Service definition
fields](#service-definition-fields). Here, we are creating two services: The
application service `python-todo` (a simple Flask todo application defined in
the `sample-apps` directory) depends on `appdb` (a Postgresql container),
specified through the `dependencies` field. As in `docker-compose`, this means
that `python-todo` will get started after `appdb` reaches running status.

The `miniboss.cli` function is the main entry point; you need to execute it
in the main routine of your scirpt. Let's run this script without arguments,
which leads to the following output:

```
Usage: miniboss-main.py [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  start
  stop
```

We can start our small ensemble of services by running `./miniboss-main.py
start`. After spitting out some logging text, you will see that starting the
containers failed, with the `python-todo` service throwing an error that it
cannot reach the database. The reason for this error is that the Postgresql
process has started, but is still initializing, and does not accept connections
yet. The standard way of dealing with this issue is to include backoff code in
your application that checks on the database port regularly, until the
connection is accepted. `miniboss` offers an alternative with [lifecycle
events](#lifecycle-events). For the time being, you can simply rerun
`./miniboss-main.py start`, which will restart only the `python-todo`
service, as the other one is already running. You should be able to navigate to
`http://localhost:8080` and view the todo app page.

You can also exclude services from the list of services to be started with the
`--exclude` argument; `./miniboss-main.py start --exclude python-todo` will
start only `appdb`. If you exclude a service that is depended on by another, you
will get an error. If a service fails to start (i.e. container cannot be started
or the lifecycle events fail), it and all the other services that depend on it
are registered as failed.

### Stopping services

Once you are done working, you can stop the running services with
`miniboss-main.py stop`. This will stop the services in the reverse order of
dependency, i.e. first `python-todo` and then `appdb`. Exclusion is possible
also when stopping services with the same `--exclude` argument. Running
`./miniboss-main.py stop --exclude appdb` will stop only the `python-todo`
service. If you exclude a service whose dependency will be stopped, you will get
an error.

### Reloading a service

miniboss also allows you to reload a specific service by building a new
container image from a directory. You need to provide the path to the directory
in which the Dockerfile and code of a service resides in order to use this
feature. You can also provide an alternative Dockerfile name. Here is an
example:

```
class Application(miniboss.Service):
    name = "python-todo"
    image = "afroisalreadyin/python-todo:0.0.1"
    env = {"DB_URI": "postgresql://dbuser:dbpwd@appdb:5432/appdb"}
    dependencies = ["appdb"]
    ports = {8080: 8080}
    build_from_directory = "python-todo/"
	dockerfile = "Dockerfile"
```

The `build_from_directory` option has to be a path relative to the main miniboss
file. With such a service configuration, you can run `./miniboss-main.py reload
python-todo`, which will build the container image, stop the running service
container, and restart the new image. Since [the context](#the-global-context)
generated at start is saved in a file, these context values are available to the
new container.

## Lifecycle events

`miniboss.Service` has two methods that can be overriden in order to correctly
change states and execute actions on the container:

- **`Service.pre_start()`**: Executed before the service is started. Can be used
  for things like initializing mount directory contents.

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

Both of these methods do nothing by default. A service is not registered as
properly started before both of these lifecycle methods are processed
successfully; only then are the dependant services started.

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

## Ports and hosts

miniboss starts services on an isolated bridge network, mapping no ports by
default. On this network, services can contact each other on the ports that the
applications are listening on. The `appdb` Postgresql service above, for
example, can be contacted on the port 5432, the default port on which Postgresql
listens. This is the reason the host part of the `DB_URI` environment variable
on the `python-todo` service is `appdb:5432`. If you want to reach `appdb` on
the port `5432` from the host system, which would be necessary to implement the
ping method, you need to make this mapping explicit with the `ports` field of
the service definition. This field accepts a dictionary of int keys and int
values. The key is the service container port, and the value is the host port.
In the case of `appdb`, the Postgresql port of the container is mapped to port
5433 on the local machine, in order not to collide with any local Postgresql
instances.

### The global context

The object `miniboss.Context`, derived from the standard dict, can be used to
store values that are accessible to other service definitions, especially in the
`env` field. For example, if you create a user in the `post_start` method of a
service, and would like to make the ID of this user available to a dependant
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

When a container set is started, the context that is generated is saved at the
end in the file `.miniboss-context`, in order to be used when the same
containers are restarted or a specific service is
[reloaded](#reloading-a-service).

## Service definition fields

- **`name`**: The name of the service. Must be non-empty and unique. The
    container can be contacted on the network under this name; must therefore be
    a valid hostname.

- **`image`**: Container image of the service. Must be non-empty.

- **`dependencies`**: A list of the dependencies of a service by name. If there
    are any invalid or circular dependencies, an error will be raised.

- **`env`**: Environment variables to be injected into the service container, as a
    dict. The values of this dict can contain extrapolations from the global
    context; these extrapolations are executed when the service starts.

- **`ports`**: A mapping of the ports that must be exposed on the running host.
    Keys are ports local to the container, values are the ports of the running
    host. See [Ports and hosts](#ports-and-hosts) for more details on
    networking.

- **`volumes`**: Directories to be mounted inside the servicesas a volume, and
  the mount points. The value can be either a list of strings, in the format
  `"directory:mount_point:mode"`, or in the dictionary format `{directory:
  {"bind": mount_point, "mode": mode}}`. In both cases, `mode` is optional. See
  the [Using
  volumes](https://docker-py.readthedocs.io/en/stable/api.html#docker.api.container.ContainerApiMixin.create_container)
  section of Python SDK documentation for details.

- **`always_start_new`**: Whether to create a new container each time a service is
    started or restart an existing but stopped container. Default value is
    `False`, meaning that by default existing container will be restarted.

- **`stop_signal`**: Which stop signal Docker should use to stop the container by
    name (not by integer value, so don't use values from the `signal` standard
    library module here). Default is `SIGTERM`. Accepted values are `SIGINT`,
    `SIGTERM`, `SIGKILL` and `SIGQUIT`.

- **`build_from_directory`**: The directory from which a service can be
    reloaded. It should be either absolute, or relative to the main script.
    Required if you want to reload a service.

- **`dockerfile`**: Dockerfile to use when building a service from the
  `build_from_directory`. Default is `Dockerfile`.

## Todos

- [x] Add linting
- [x] Pull containers
- [x] Integration tests
- [x] Mounting volumes
- [x] pre-start lifetime event
- [ ] Running one-off containers
- [ ] Configuration object extrapolation
- [ ] Read specs from docker-compose.yml
- [ ] Running tests once system started
- [ ] Using context values in tests
- [ ] Dependent test suites and setups
- [x] Bug: context values when reloading a service
- [x] Derive exceptions from a base `MinibossException`
- [x] Don't use existing container if env changed
- [x] Build and restart a container
- [x] Stop signal as an option on service def
