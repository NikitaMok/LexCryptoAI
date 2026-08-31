import json

from app.llm.clauses import analyze_clauses
from app.llm.client import LlmReply
from app.parsing.document import Document, SourceFormat
from app.rules.contract import ContractView


def _view(text: str) -> ContractView:
    lines = [line for line in text.strip().split("\n") if line.strip()]
    return ContractView.from_document(Document(SourceFormat.DOCX, lines))


COMPLIANT_SNIPPET = """
1.1. Настоящий Договор является внешнеторговым договором между ООО «Уралимпорт»,
ИНН 6659123456, и Shenzhen Precision Machinery Co., Ltd.
1.2. Если сторона действует как агент, комиссионер или поверенный, она указывает
договор, в интересах которого действует.
"""


class TestClauseAnalysis:
    def test_grounded_quote_is_kept(self):
        payload = {
            "parties": [
                {"name": "ООО «Уралимпорт»", "inn": "6659123456", "role": "покупатель"}
            ],
            "notes": [
                {
                    "code": "FTC-004",
                    "present": True,
                    "quote": "Если сторона действует как агент, комиссионер или поверенный",
                    "reading": "в договоре названы агент, комиссионер и поверенный",
                }
            ],
        }
        result = analyze_clauses(
            _view(COMPLIANT_SNIPPET),
            complete_fn=lambda prompt: LlmReply(text=json.dumps(payload), model="test"),
        )

        assert result.available
        assert result.parties[0].inn == "6659123456"
        assert result.notes[0].code == "FTC-004"
        assert "агент" in result.notes[0].quote

    def test_invented_quote_is_dropped(self):
        payload = {
            "parties": [],
            "notes": [
                {
                    "code": "FTC-004",
                    "present": True,
                    "quote": "этой фразы в договоре нет вообще",
                    "reading": "модель додумала оговорку",
                }
            ],
        }
        result = analyze_clauses(
            _view(COMPLIANT_SNIPPET),
            complete_fn=lambda prompt: LlmReply(text=json.dumps(payload), model="test"),
        )

        assert result.notes[0].quote == ""

    def test_article_citation_in_reading_is_dropped(self):
        payload = {
            "parties": [],
            "notes": [
                {
                    "code": "AST-003",
                    "present": True,
                    "quote": "внешнеторговым договором",
                    "reading": "это следует из ст. 99 ч. 12 282-ФЗ",
                }
            ],
        }
        result = analyze_clauses(
            _view(COMPLIANT_SNIPPET),
            complete_fn=lambda prompt: LlmReply(text=json.dumps(payload), model="test"),
        )

        assert result.notes[0].reading == ""

    def test_unknown_rule_code_is_ignored(self):
        payload = {
            "parties": [],
            "notes": [{"code": "FAKE-001", "present": True, "quote": "", "reading": ""}],
        }
        result = analyze_clauses(
            _view(COMPLIANT_SNIPPET),
            complete_fn=lambda prompt: LlmReply(text=json.dumps(payload), model="test"),
        )

        assert result.notes == ()

    def test_unavailable_model_does_not_raise(self):
        result = analyze_clauses(
            _view(COMPLIANT_SNIPPET),
            complete_fn=lambda prompt: LlmReply(text="", model="test", error="Ollama недоступна"),
        )

        assert not result.available
        assert "недоступна" in result.detail

    def test_circumvention_in_reading_is_dropped(self):
        payload = {
            "parties": [],
            "notes": [
                {
                    "code": "THR-003",
                    "present": True,
                    "quote": "внешнеторговым договором",
                    "reading": "раздробите платёж на части",
                }
            ],
        }
        result = analyze_clauses(
            _view(COMPLIANT_SNIPPET),
            complete_fn=lambda prompt: LlmReply(text=json.dumps(payload), model="test"),
        )

        assert result.notes[0].reading == ""
