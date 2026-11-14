"""Setup script for Jarvis."""

from setuptools import setup, find_packages

setup(
    name="jarvis",
    version="0.1.0",
    description="Personal AI Butler - completes assignments, manages emails, calendar, GitHub, finances, and more",
    author="You",
    packages=find_packages(where=".", include=["jarvis*"]),
    package_dir={"": "."},
    python_requires=">=3.11",
    install_requires=[
        "pydantic>=2.8",
        "pydantic-settings>=2.3",
        "python-dotenv>=1.0",
        "pyyaml>=6.0",
        "httpx>=0.27",
        "aiohttp>=3.9",
        "websockets>=12.0",
        "cryptography>=42.0",
        "google-auth>=2.29",
        "google-auth-oauthlib>=1.2",
        "google-auth-httplib2>=0.2",
        "google-api-python-client>=2.118",
        "pygithub>=2.1",
        "gitpython>=3.1",
        "plaid-python>=12.0",
        "yfinance>=0.2",
        "pyobjc-framework-ApplicationServices>=10.2",
        "pyobjc-framework-Cocoa>=10.2",
        "appscript>=1.1.0",
        "openai-whisper>=20231117",
        "pyttsx3>=2.99",
        "apscheduler>=3.10",
        "typer>=0.12",
        "rich>=13.7",
        "loguru>=0.7",
        "tenacity>=8.2",
        "python-dateutil>=2.9",
        "croniter>=2.0",
        "watchdog>=4.0",
    ],
    extras_require={
        "dev": [
            "pytest>=8.2",
            "pytest-asyncio>=0.23",
            "pytest-mock>=3.14",
            "ruff>=0.4",
            "mypy>=1.10",
            "pre-commit>=3.7",
        ],
        "voice": [
            "faster-whisper>=1.0",
            "piper-tts>=1.2",
        ],
        "browser": [
            "browser-use>=0.1",
            "playwright>=1.44",
        ],
    },
    entry_points={
        "console_scripts": [
            "jarvis=jarvis.__main__:app",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)