#! /usr/bin/env python3
import miniboss
import psycopg2

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
    image = "afroisalreadyin/python-todo:0.0.1"
    env = {"DB_URI": "postgresql://dbuser:dbpwd@appdb:5432/appdb"}
    dependencies = ["appdb"]
    ports = {8080: 8080}
    stop_signal = "SIGINT"
    build_from = 'python-todo'

if __name__ == "__main__":
    miniboss.cli()
