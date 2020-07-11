#! /usr/bin/env python3
import drillmaster

DB_PORT = 5433

class Database(drillmaster.Service):
    name = "appdb"
    image = "postgres:10.6"
    env = {"POSTGRES_PASSWORD": "dbpwd",
           "POSTGRES_USER": "dbuser",
           "POSTGRES_DB": "appdb",
           "PGPORT": DB_PORT }
    ports = {DB_PORT: DB_PORT}

class Application(drillmaster.Service):
    name = "python-todo"
    image = "python-todo:0.0.1"
    env = {"DB_URI": "localhost:{:d}".format(DB_PORT)}
    dependencies = ["appdb"]

if __name__ == "__main__":
    drillmaster.cli()
