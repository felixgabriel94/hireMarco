from hiremarco.mix.inventory import LOGIC_STOCK, by_kind, installed


def test_inventory_reads_component_bundles_and_logic_stock(tmp_path):
    for name in ("FabFilter Pro-Q 3", "ValhallaVintageVerb", "Diva"):
        (tmp_path / f"{name}.component").mkdir()
    names = installed([tmp_path])
    assert "FabFilter Pro-Q 3" in names and "Space Designer" in names and len(names) == len(LOGIC_STOCK) + 3
    grouped = by_kind(names)
    assert "FabFilter Pro-Q 3" in grouped["eq"] and "ValhallaVintageVerb" in grouped["reverb"]
    assert "Diva" not in sum(grouped.values(), [])  # an instrument, not an effect
