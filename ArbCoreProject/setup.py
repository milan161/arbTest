from setuptools import setup, find_packages

setup(
    name="arbcore",
    version="0.1.0",
    description="量化交易公共基座库 (Shared Core Library)",
    author="Quant Developer",
    packages=find_packages(),
    install_requires=[
        "requests",
        "pandas",
        "beautifulsoup4",
        "lxml"
    ],
)