from scripts.eval_fixtures import main


def test_sample_contracts_keep_expected_colours():
    assert main() == 0
