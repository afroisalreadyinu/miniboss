[![afroisalreadyinu](https://circleci.com/gh/afroisalreadyinu/miniboss.svg?style=svg)](https://app.circleci.com/pipelines/github/afroisalreadyinu/miniboss)

# miniboss

miniboss is a Python application that can be used to locally start multiple
dependent docker services, individually rebuild and restart them, and run
initialization jobs. The definitions for services can be written in Python,
allowing you to use

## Why not docker-compose?

First and foremost, this is not YAML. `docker-compose` is in the school of
yaml-as-service-description, which means that going beyond a static description
of a service set necessitates templates, or some kind of scripting. One could as
well use a full-blown programming language, while trying to keep simple things
simple. Another thing sorely missing in `docker-compose` is lifecycle hooks,
i.e. a mechanism whereby scripts can be executed when the state of a container
changes. Lifecycle hooks have been
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

## Lifecycle events

`miniboss.Service` has two methods that can be overriden in order to move it
to the correct states and execute actions on the container:

- **`Service.ping()`**: Executed repeatedly right after the service starts with
  a 0.1 second delay between executions. If this method does not return `True`
  within a given timeout value (can be set with the `--timeout` argument,
  default is 300 seconds), the service is registered as failed. Any exceptions
  in this method will be propagated, and also cause the service to fail.

- **`Service.post_start_init()`**: This method is executed after a successful
  `ping`. It can be used to prime a service by e.g. creating data on it, or
  bringing it to a certain state. You can also use the global context in this
  method; see [The global context](#the-global-context) for details.

Both of these methods do nothing by default.

## Ports and hosts

TBW

### The global context

The object `miniboss.Context`, derived from the standard dict, can be used to
store values that are accessible to other service definitions, especially in the
`env` field.

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

- **`always_start_new`**: Whether to create a new container each time a service is
    started or restart an existing but stopped container. Default value is
    `False`, meaning that by default existing container will be restarted.

- **`stop_signal`**: Which stop signal Docker should use to stop the container by
    name (not by integer value, so don't use values from the `signal` standard
    library module here). Default is `SIGTERM`. Accepted values are `SIGINT`,
    `SIGTERM`, `SIGKILL` and `SIGQUIT`.

## Todos

- [ ] Build and restart a container
- [ ] Don't use existing container if env changed
- [x] Stop signal as an option on service def
