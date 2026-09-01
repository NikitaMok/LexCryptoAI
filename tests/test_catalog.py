import yaml

from app.core.catalog import CATALOG_PATH, load_catalog


def test_catalog_loads():
    catalog = load_catalog()

    assert CATALOG_PATH.is_file()
    assert catalog.llm.provider == "ollama"
    assert catalog.llm.model
    assert catalog.wallet
    assert catalog.counterparty


def test_default_model_in_yaml():
    payload = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))

    assert payload["llm"]["model"] == "llama3.3:70b"
    assert payload["llm"]["provider"] == "ollama"


def test_free_sources_are_on_by_default():
    catalog = load_catalog()

    assert {item.id for item in catalog.enabled("wallet", tier="free")} >= {
        "trongrid",
        "etherscan",
        "goplus",
    }
    assert {item.id for item in catalog.enabled("counterparty", tier="free")} >= {
        "egrul",
        "rusprofile",
        "saby",
        "opencorporates",
        "gleif",
    }


def test_paid_sources_are_off_by_default():
    catalog = load_catalog()

    paid_wallet = [item.id for item in catalog.wallet if item.tier == "paid"]
    paid_party = [item.id for item in catalog.counterparty if item.tier == "paid"]

    assert paid_wallet
    assert paid_party
    assert catalog.enabled("wallet", tier="paid") == []
    assert catalog.enabled("counterparty", tier="paid") == []


def test_paid_without_key_is_not_ready():
    catalog = load_catalog()

    assert catalog.uses("wallet", "trongrid")
    assert catalog.uses("counterparty", "egrul")
    assert not catalog.uses("wallet", "chainalysis")
    assert not catalog.uses("counterparty", "kontur_focus")


def test_paid_entries_name_env_key_and_module():
    catalog = load_catalog()

    for item in catalog.wallet + catalog.counterparty:
        if item.tier != "paid":
            continue
        assert item.env_key, f"{item.id}: у платного источника нет env_key"
        assert item.module, f"{item.id}: у платного источника нет module"
        assert not item.enabled
