import os
from setuptools import setup

long_description = """
miniboss is a Python application for locally running multiple dependent docker
services, individually rebuilding and restarting them, and managing application
state with lifecycle hooks. Services definitions can be written in Python,
allowing the use of programming logic instead of markup.
"""

setup(
    name = "miniboss",
    version = "0.2.0",
    author = "Ulas Turkmen",
    description = "Containerized app testing framework",
    long_description = long_description,
    install_requires = [],
    tests_require = [],
    packages=['miniboss'],
    url = "https://github.com/afroisalreadyinu/miniboss",
    license = "MIT",
    classifiers = [
        "License :: OSI Approved :: MIT License",
        "Development Status :: 3 - Alpha",
        "Topic :: Software Development :: Build Tools",
        "Topic :: Software Development :: Testing",
        "Programming Language :: Python :: 3",
        "Intended Audience :: Developers"
    ]
)
