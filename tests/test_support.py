"""Tests for Level 1 portal support answers."""

import pytest

from app.support import ARTICLES, answer_support_question


@pytest.mark.parametrize(
    ("question", "topic", "expected_text"),
    [
        ("How do I upload and process a PDF?", "uploads", "50 MB"),
        ("How are costs calculated per customer?", "costs", "Azure Cost Management"),
        ("How is Azure AI token usage priced?", "tokens", "illustrative only"),
        ("How long can I keep files?", "retention", "10 years"),
        ("Does my document go to a third-party AI?", "privacy", "local Docker"),
    ],
)
def test_routes_common_level_one_questions(
    question: str,
    topic: str,
    expected_text: str,
) -> None:
    response = answer_support_question(question)

    assert response["topic"] == topic
    assert expected_text in str(response["answer"])
    assert response["matched"] is True
    assert response["escalate"] is False
    assert response["suggestions"]
    assert response["links"]


def test_does_not_invent_an_answer_outside_portal_support() -> None:
    response = answer_support_question("Who won the football championship?")

    assert response["topic"] == "unknown"
    assert response["matched"] is False
    assert response["escalate"] is True
    assert "portal administrator" in str(response["answer"])


@pytest.mark.parametrize(
    "question",
    sorted({suggestion for article in ARTICLES for suggestion in article.suggestions}),
)
def test_every_suggested_question_routes_to_a_known_topic(question: str) -> None:
    response = answer_support_question(question)

    assert response["topic"] != "unknown", question