"""
shm_comm — Shared Memory Communication Library

A ZMQ/TCP-style IPC library using shared memory for ultra-low latency
communication between Python processes on the same machine.
"""

from setuptools import setup, find_packages
from pathlib import Path

long_description = (Path(__file__).parent / "README.md").read_text(encoding="utf-8")

setup(
    name="shm-comm",
    version="1.0.0",
    author="RAFT Robotics",
    description=(
        "ZMQ-style IPC using shared memory for ultra-low latency "
        "inter-process communication."
    ),
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(exclude=["tests*", "examples*"]),
    python_requires=">=3.10",
    install_requires=[
        "numpy>=1.21",
    ],
    extras_require={
        "msgpack": ["msgpack>=1.0"],
        "dev": [
            "pytest>=7.0",
            "pytest-timeout",
            "msgpack>=1.0",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: POSIX :: Linux",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: MacOS",
        "Intended Audience :: Developers",
        "Topic :: System :: Networking",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
