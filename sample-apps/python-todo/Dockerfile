FROM python:3.5

WORKDIR /opt/python-todo

COPY . .

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

CMD ["python3", "app.py"]
