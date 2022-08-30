import os
from datetime import datetime

from flask import Flask, redirect, render_template, request
from flask_sqlalchemy import SQLAlchemy

app = Flask("todo-app")

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["DB_URI"]
db = SQLAlchemy(app)


class TodoItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    what_to_do = db.Column(db.String, nullable=False)


@app.route("/")
def index():
    return render_template("index.html", todos=TodoItem.query.all())


@app.route("/add/", methods=["POST"])
def add_todo():
    new_todo = TodoItem(what_to_do=request.form["what-to-do"])
    db.session.add(new_todo)
    db.session.commit()
    return redirect("/")


if __name__ == "__main__":
    db.create_all()
    app.run(host="0.0.0.0", port=8080)
