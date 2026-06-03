from setuptools import setup, find_packages

setup(
    name="arbcore",
    version="1.0.0",
    description="量化交易公共基座库 (Industrial Grade Core Library)",
    author="Gemini CLI",
    packages=find_packages(),
    install_requires=[
        "requests>=2.31.0",
        "pandas>=2.1.4",
        "numpy>=1.26.2",
        "beautifulsoup4",
        "lxml",
        "pyyaml",
        "paramiko",
        "flask",
        "flask-socketio",
        "yfinance",
        "plotly"
    ],
)