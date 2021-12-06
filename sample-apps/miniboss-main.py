#! /usr/bin/env python3
import miniboss
import psycopg2

miniboss.group_name('readme-demo')

class Database(miniboss.Service):
    name = "appdb"
    image = "postgres:10.6"
    env = {"POSTGRES_PASSWORD": "dbpwd",
           "POSTGRES_USER": "dbuser",
           "POSTGRES_DB": "appdb" }
    ports = {5432: 5433}

    def ping(self):
        try:
            connection = psycopg2.connect("postgresql://dbuser:dbpwd@localhost:5433/appdb")
            cur = connection.cursor()
            cur.execute('SELECT 1')
        except psycopg2.OperationalError:
            return False
        else:
            return True

class Application(miniboss.Service):
    name = "python-todo"
    image = "python-todo:latest"
    env = {"DB_URI": "postgresql://dbuser:dbpwd@appdb:5432/appdb"}
    dependencies = ["appdb"]
    ports = {8080: 8080}
    stop_signal = "SIGINT"
    build_from = 'python-todo'

def print_info(services):
    if Application.name in services:
        print("TODO app can be accessed at http://localhost:8080")

miniboss.on_start_services(print_info)

if __name__ == "__main__":
    miniboss.cli()
