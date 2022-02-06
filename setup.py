#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re

from setuptools import setup


def get_version(package):
    """
    Return package version as listed in `__version__` in `init.py`.
    """
    path = os.path.join(package, "__init__.py")
    init_py = open(path, "r", encoding="utf8").read()
    return re.search("__version__ = ['\"]([^'\"]+)['\"]", init_py).group(1)


def get_long_description():
    """
    Return the README.
    """
    return open("README.markdown", "r", encoding="utf8").read()


def get_packages(package):
    """
    Return root package and all sub-packages.
    """
    return [
        dirpath
        for dirpath, dirnames, filenames in os.walk(package)
        if os.path.exists(os.path.join(dirpath, "__init__.py"))
    ]


env_marker_cpython = (
    "sys_platform != 'win32'"
    " and (sys_platform != 'cygwin'"
    " and platform_python_implementation != 'PyPy')"
)

env_marker_win = "sys_platform == 'win32'"
env_marker_below_38 = "python_version < '3.8'"
env_marker_below_37 = "python_version < '3.7'"
env_marker_gte_37 = "python_version >= '3.7'"

minimal_requirements = [
    "click>=7.0",
    "typing-extensions;" + env_marker_below_38,
]


extra_requirements = [
    "uvloop>=0.14.0,!=0.15.0,!=0.15.1; " + env_marker_cpython,
    "colorama>=0.4;" + env_marker_win,
    "watchgod>=0.6",
    "python-dotenv>=0.13",
    "PyYAML>=5.1",
]


setup(
    name="uvicontainer",
    version=get_version("uvicontainer"),
    url="https://github.com/ProjectHentai/uvicorn",
    license="BSD",
    description="The lightning-fast tcp and udp server.",
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    author="Tom Christie",
    author_email="tom@tomchristie.com",
    packages=get_packages("uvicontainer"),
    install_requires=minimal_requirements,
    extras_require={"standard": extra_requirements},
    include_package_data=True,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
    ],
    entry_points="""
    [console_scripts]
    uvicontainer=uvicontainer.main:main
    """,
    project_urls={
        "Funding": "https://github.com/sponsors/encode",
        "Source": "https://github.com/encode/uvicorn",
        "Changelog": "https://github.com/encode/uvicorn/blob/master/CHANGELOG.md",
    },
)
