import os
from setuptools import setup

with open('README.md', 'r', encoding='utf-8') as f:
    long_description = f.read()

setup(
    name = "miniboss",
    version = "0.4.3",
    author = "Ulas Turkmen",
    description = "Containerized app testing framework",
    long_description = long_description,
    long_description_content_type='text/markdown',
    install_requires = ["click>7", "docker>4", "furl>2", "requests>2", "attrs>20", "python-slugify>6.0.0"],
    python_requires='>3.8.0',
    tests_require = ["pytest>5.4"],
    packages=['miniboss'],
    package_data={"miniboss": ["py.typed"]},
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
