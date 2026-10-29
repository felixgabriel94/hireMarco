import json

from hiremarco.studio.vault import Vault, find_serials

RECEIPT = """Thank you for your order 8571784
Order total: 199.00

Massive X
Serial number: AB12C-DE34F-GH56J-KL78M-NP90Q

VocalSynth 2
License key: SN-VS2-1234-5678-ABCD
Invoice 63136921
"""


class MemoryKeychain:
    def __init__(self):
        self.store = {}

    def put(self, item, value):
        self.store[item] = value

    def get(self, item):
        return self.store.get(item)

    def items(self):
        return sorted(self.store)


def test_find_serials_reads_labelled_values_and_their_products():
    found = find_serials("Native Instruments", "Download details", RECEIPT)
    assert [(f.product, f.value) for f in found] == [
        ("Massive X", "AB12C-DE34F-GH56J-KL78M-NP90Q"), ("VocalSynth 2", "SN-VS2-1234-5678-ABCD")]
    assert found[0].tail == "P90Q"


def test_order_and_invoice_numbers_are_not_serials():
    assert find_serials("UA", "Thank you", "Order Number: 101705158\nSerial: 12345\nInvoice 63136921") == []


def test_keep_returns_pointers_only_and_puts_values_in_the_keychain():
    keychain = MemoryKeychain()
    pointers = Vault(keychain=keychain, ask=lambda r: True).keep([("Native Instruments", "Order", RECEIPT)])
    assert pointers == ["Native Instruments: Massive X (serial in Keychain, ends in P90Q)",
                        "Native Instruments: VocalSynth 2 (serial in Keychain, ends in ABCD)"]
    assert all("AB12C" not in p for p in pointers)
    assert keychain.get("Native Instruments: Massive X") == "AB12C-DE34F-GH56J-KL78M-NP90Q"


def test_show_asks_the_owner_and_logs_without_the_value(tmp_path):
    keychain = MemoryKeychain()
    keychain.put("Waves: Ultimate", "XYZ-123-456-789")
    log = tmp_path / "vault.jsonl"
    assert Vault(keychain=keychain, log_path=log, ask=lambda r: False).show("Waves: Ultimate") is None
    assert Vault(keychain=keychain, log_path=log, ask=lambda r: True).show("Waves: Ultimate") == "XYZ-123-456-789"
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert [line["outcome"] for line in lines] == ["refused", "shown"]
    assert "XYZ" not in log.read_text()


def test_a_serial_on_the_line_after_its_label_is_found_with_the_named_product():
    text = "Thanks for reaching out.\n### Serial Number for *VocalSynth 2*:\n\nSN-ABCD1-EF2G-HIJ3-KLMN-OPQR\n"
    found = find_serials("iZotope", "Re: support", text)
    assert [(f.product, f.tail) for f in found] == [("VocalSynth 2", "OPQR")]


def test_request_ids_shaped_like_uuids_are_not_serials():
    text = "Location reset number:\n0ab123c4-56d7-89e0-1fab-23c4567de8fa\n"
    assert find_serials("iLok", "Location Reset Approved", text) == []


def test_a_label_in_emphasis_is_not_a_product_and_a_known_name_in_the_subject_is():
    text = "### Here is your *serial number*:\n\nSN-ABCD1-EF2G-HIJ3-KLMN-ZUBH\n"
    found = find_serials("iZotope", "Re: re download my VocalSynth 2 plugin", text, known=["VocalSynth 2", "Neutron 3"])
    assert [(f.product, f.tail) for f in found] == [("VocalSynth 2", "ZUBH")]
