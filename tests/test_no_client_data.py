"""The repository is public: client data lives in Marco's state folder on the client's Mac, never here."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT_FILES = {"license_ledger.json", "plans.json", "accounts.json", "logic_plugins.json", "not_owned.json",
                "plugin_bundles.json", "learned_plugins.json", "chain.txt", "flex.txt", "jobs.jsonl", "env"}


def test_no_client_data_files_in_the_repository():
    found = [p.relative_to(ROOT) for p in ROOT.rglob("*")
             if p.name in CLIENT_FILES and ".venv" not in p.parts and ".git" not in p.parts]
    assert found == []
