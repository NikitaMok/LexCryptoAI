from app.norms.index import Norm
from app.norms.vectors import corpus_fingerprint, load_vectors, save_vectors


def _norm(article: str, text: str) -> Norm:
    return Norm(act="282-ФЗ", article=article, article_title="", text=text)


def test_roundtrip_preserves_vectors(tmp_path):
    path = tmp_path / "norm_vectors.bin"
    pairs = [("282-ФЗ, ст. 1", [1.0, 0.0, 0.5]), ("173-ФЗ, ст. 19 ч. 9", [0.0, 1.0, 0.25])]
    save_vectors(path, model_name="mini", fingerprint="abc", pairs=pairs)

    loaded = load_vectors(path, model_name="mini", fingerprint="abc")

    assert loaded is not None
    assert loaded["282-ФЗ, ст. 1"][0] == 1.0
    assert loaded["173-ФЗ, ст. 19 ч. 9"][1] == 1.0


def test_stale_fingerprint_is_ignored(tmp_path):
    path = tmp_path / "norm_vectors.bin"
    save_vectors(path, model_name="mini", fingerprint="abc", pairs=[("a", [1.0, 0.0])])

    assert load_vectors(path, model_name="mini", fingerprint="other") is None
    assert load_vectors(path, model_name="other", fingerprint="abc") is None


def test_fingerprint_changes_with_text():
    first = [_norm("1", "репатриация")]
    second = [_norm("1", "депозитарий")]

    assert corpus_fingerprint(first, "m") != corpus_fingerprint(second, "m")
    assert corpus_fingerprint(first, "m") != corpus_fingerprint(first, "other")


def test_truncated_file_is_ignored(tmp_path):
    path = tmp_path / "norm_vectors.bin"
    path.write_bytes(b"LXE1broken")

    assert load_vectors(path, model_name="mini", fingerprint="abc") is None
