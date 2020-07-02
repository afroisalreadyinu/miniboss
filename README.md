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
framework, but I haven't figured out the use case yet.

## Usage

Here is a very simple service specification:

```python
#! /usr/bin/env python3
import drillmaster

DB_PORT = 5433

class Database(drillmaster.Service):
    image = "postgres:10.6"
    name = "keycloakdb"
    env = {"POSTGRES_PASSWORD": "keycloakdbpwd",
           "POSTGRES_USER": "keycloak",
           "POSTGRES_DB": "keycloak",
           "PGPORT": KEYCLOAK_DB_PORT}
    ports = {DB_PORT: DB_PORT}

class Application(drillmaster.Service):
    pass
```