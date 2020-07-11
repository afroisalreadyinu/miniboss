[![afroisalreadyinu](https://circleci.com/gh/afroisalreadyinu/drillmaster.svg?style=svg)](https://app.circleci.com/pipelines/github/afroisalreadyinu/drillmaster)

# drillmaster

drillmaster is a Python application that can be used to locally start multiple
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
import drillmaster

class Database(drillmaster.Service):
    name = "appdb"
    image = "postgres:10.6"
    env = {"POSTGRES_PASSWORD": "dbpwd",
           "POSTGRES_USER": "dbuser",
           "POSTGRES_DB": "appdb",
           "PGPORT": 5433 }
    ports = {5433: 5433}

class Application(drillmaster.Service):
    name = "python-todo"
    image = "afroisalreadyin/python-todo:0.0.1"
    env = {"DB_URI": "postgresql://dbuser:dbpwd@localhost:5433/appdb"}
    dependencies = ["appdb"]

if __name__ == "__main__":
    drillmaster.cli()
```

A **service** is defined by subclassing `drillmaster.Service` and overriding, in
the minimal case, the fields `image` and `name`. The `env` field specifies the
enviornment variables; as in the case of the `appdb` service, you can use
ordinary variables in this and any other value. The other available fields will
be explained later. The application service `Application` depends on `appdb`,
specified with the `dependencies` field. As in `docker-compose`, this means that
it will get started after `Database` reaches running status.

The `drillmaster.cli` function is the main entry point; you need to execute it
in the main routine of your scirpt. Let's run this script without arguments,
which leads to the following output:

```
Usage: drillmaster-main.py [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  start
  stop
```

We can start our small ensemble of services by running `./drillmaster-main.py
start`.


### Lifecycle events

A service has two methods that can be overriden: `ping` and `post_start_init`.
Both of these by default do nothing; when implemented, they are executed one
after the other, and the service is not registered as `running` before each
succeed. The `ping` method is executed repeatedly, with 0.1 seconds gap, for
`timeout` seconds, until it returns True. Once `ping` returns, `post_start_init`
is called.