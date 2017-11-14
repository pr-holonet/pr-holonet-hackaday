from setuptools import setup, find_packages
from os import path

from holonet import version

here = path.abspath(path.dirname(__file__))

setup(
    name='holonet-web',
    version=version.__version__,

    description='',
    long_description='',

    packages=find_packages(exclude=['.eggs', 'node_modules']),

    setup_requires=['pytest-runner', 'setuptools-pep8', 'setuptools-lint'],
    tests_require=['pytest'],
)
