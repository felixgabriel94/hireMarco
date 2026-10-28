"""Every test runs sealed off from the Mac's real secrets, state and network.

Added 2026-10-28 after a test whose line fell through to the model path made
one real Muse Spark call (0.0012 USD) and wrote it to the real job log: the
env file held a live key and the job log's folder was fixed at import. Now
each test gets an empty env file and its own state folder, the secret keys
are removed from the environment, and any real network connection fails.
"""

import socket

import pytest

from hiremarco import config, joblog

SECRET_KEYS = [k for k in config.KNOWN_KEYS]


@pytest.fixture(autouse=True)
def sealed(tmp_path, monkeypatch):
    env = tmp_path / "sealed.env"
    env.write_text("")
    monkeypatch.setenv("HIREMARCO_ENV", str(env))
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(joblog, "STATE_DIR", tmp_path)
    for key in SECRET_KEYS:
        monkeypatch.delenv(key, raising=False)

    def no_network(*args, **kwargs):
        raise OSError("tests do not reach the network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
