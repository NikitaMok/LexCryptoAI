from app.norms.hybrid import fuse
from app.norms.index import Norm
from app.norms.search import SearchHit


def _norm(article: str, text: str, act: str = "282-ФЗ") -> Norm:
    return Norm(act=act, article=article, article_title="", text=text)


def _hit(article: str, text: str, score: float) -> SearchHit:
    return SearchHit(norm=_norm(article, text), score=score)


def test_fusion_promotes_item_present_in_both_lists():
    lexical = [_hit("1", "лексика", 10), _hit("2", "только bm25", 9)]
    dense = [_hit("3", "только вектор", 0.9), _hit("1", "лексика", 0.8)]

    merged = fuse(lexical, dense, limit=3)

    assert merged[0].norm.article == "1"
    assert {hit.norm.article for hit in merged} == {"1", "2", "3"}


def test_fusion_respects_limit():
    lexical = [_hit(str(n), "текст", 10 - n) for n in range(8)]

    assert len(fuse(lexical, limit=3)) == 3
