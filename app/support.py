"""Answer Level 1 questions from a curated Papertrail support knowledge base."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SupportArticle:
    """Describe one supported portal topic and its matching vocabulary."""

    id: str
    title: str
    answer: str
    keywords: tuple[str, ...]
    href: str
    link_label: str
    suggestions: tuple[str, ...]


ARTICLES = (
    SupportArticle(
        id="getting-started",
        title="About Papertrail",
        answer=(
            "Papertrail turns native or scanned PDF files into structured JSON. It extracts "
            "text locally, can compare two of five local models, keeps each customer in a separate "
            "workspace, and shows document, storage, retention, and estimated cost details."
        ),
        keywords=("what is papertrail", "what does", "portal", "getting started", "start", "overview", "help"),
        href="/",
        link_label="Open the processor",
        suggestions=("How do I process a PDF?", "Are my documents private?", "How are costs calculated?"),
    ),
    SupportArticle(
        id="uploads",
        title="Uploading PDFs",
        answer=(
            "On the Processor page, choose a customer workspace and one or two analysis models, "
            "then drop in up to 10 PDF files and select Process documents. Each PDF can be up to "
            "50 MB and 500 pages. Empty, malformed, encrypted, or non-PDF files are rejected."
        ),
        keywords=("upload", "add file", "pdf", "process a document", "process pdf", "batch", "50 mb", "500 pages", "file limit"),
        href="/",
        link_label="Go to uploads",
        suggestions=("Which AI model should I choose?", "Why was my PDF rejected?", "Where do I find the result?"),
    ),
    SupportArticle(
        id="processing",
        title="Document processing",
        answer=(
            "Papertrail first reads native PDF text. Pages without enough usable text are rendered "
            "and processed with local Tesseract OCR. The worker then classifies the document, runs "
            "the selected local AI analysis, stores the result, and reports progress in the portal."
        ),
        keywords=("processing", "how does it work", "ocr", "scan", "scanned", "extract", "tesseract", "classification", "progress", "queued"),
        href="/technology",
        link_label="View processing details",
        suggestions=("Which AI model should I choose?", "What appears in the result?", "Why is processing taking time?"),
    ),
    SupportArticle(
        id="models",
        title="Local AI models",
        answer=(
            "Papertrail includes five local models. Qwen 2.5 0.5B is fastest, Qwen 2.5 1.5B "
            "is the balanced default, and Qwen 2.5 3B provides more detailed structured analysis. "
            "Llama 3.2 3B adds strong instruction following, while Gemma 3 1B provides a compact "
            "alternative. Choose up to two to compare "
            "responses against the same extracted text. Ollama runs every model locally, and the "
            "models do not read the raw PDF."
        ),
        keywords=("model", "qwen", "llama", "gemma", "ollama", "ai", "1.5b", "0.5b", "3b", "1b", "compare", "which model", "analysis model"),
        href="/logic",
        link_label="View LLM logic",
        suggestions=("How does processing work?", "Are my documents private?", "How do I compare model results?"),
    ),
    SupportArticle(
        id="results",
        title="Results and JSON",
        answer=(
            "A completed result includes extracted content, local AI analysis, cost and storage "
            "details, plain text, metadata, and warnings. Use the tabs to inspect each view or "
            "Download JSON to save the complete machine-readable result."
        ),
        keywords=("result", "json", "download", "content", "plain text", "metadata", "warning", "output", "analysis result", "compare model results"),
        href="/",
        link_label="Open results",
        suggestions=("Where is processing history?", "How are costs calculated?", "What do warnings mean?"),
    ),
    SupportArticle(
        id="history",
        title="Processing history",
        answer=(
            "Recent processing history is filtered to the customer workspace selected on the "
            "Processor page. Select a completed row to reopen its result. Queued and active rows "
            "can also be reopened to resume status tracking."
        ),
        keywords=("history", "recent", "previous", "past", "find document", "reopen", "saved run", "archive", "run status", "check status"),
        href="/",
        link_label="View run history",
        suggestions=("How do customer workspaces work?", "Where do I download JSON?", "Why is a run still queued?"),
    ),
    SupportArticle(
        id="customers",
        title="Customer workspaces",
        answer=(
            "Choose the customer workspace before processing documents. Papertrail records the "
            "customer on every run, filters history by that workspace, and maps stored files to a "
            "private customer-specific Azure container such as cust-microsoft or cust-apple."
        ),
        keywords=("customer", "workspace", "tenant", "company", "container", "separate", "isolate", "microsoft", "apple"),
        href="/#storage-portal",
        link_label="View customer storage",
        suggestions=("How is Azure storage organized?", "How do I change retention?", "Can customers see each other?"),
    ),
    SupportArticle(
        id="storage",
        title="Azure storage",
        answer=(
            "Papertrail plans two private blobs per completed document: the source PDF and its JSON "
            "result, inside that customer's cust-* container. The storage map shows blob counts, "
            "bytes, inventory status, and monthly storage estimates. Local estimate means live Azure "
            "data-plane inventory is not currently available to the app."
        ),
        keywords=("storage", "azure", "blob", "container", "stored", "storage map", "inventory", "app access pending", "local estimate", "where are files"),
        href="/#storage-portal",
        link_label="Open storage map",
        suggestions=("How do I change retention?", "What does app access pending mean?", "How much does storage cost?"),
    ),
    SupportArticle(
        id="retention",
        title="Azure lifecycle retention",
        answer=(
            "In the storage map, choose an Azure lifecycle duration from 7 days to 10 years and "
            "select Apply. The setting is saved immediately in Papertrail. Azure policy updates "
            "require the approved management identity, and Azure lifecycle deletion runs "
            "asynchronously based on each blob's last-modified age."
        ),
        keywords=("retention", "lifecycle", "duration", "delete", "deletion", "expire", "expiry", "days", "policy", "keep files"),
        href="/#storage-portal",
        link_label="Manage retention",
        suggestions=("Why does Azure say identity required?", "How is storage cost calculated?", "Where are customer files stored?"),
    ),
    SupportArticle(
        id="tokens",
        title="Token usage and Azure AI what-if",
        answer=(
            "The Tokens page reports persisted Ollama prompt and output tokens. Local Ollama has "
            "a $0 metered token charge. The Azure AI what-if multiplies prompt tokens by the "
            "configured sample input rate and output tokens by the sample output rate, then adds "
            "them. It is illustrative only, not billed usage or a live Azure retail quote. Local "
            "model compute is shown separately from recorded runtime."
        ),
        keywords=("token", "prompt token", "output token", "azure ai what if", "ollama cost", "token usage", "local compute"),
        href="/tokens",
        link_label="Open token usage",
        suggestions=("How is the Azure AI what-if calculated?", "Why is the local token charge $0?", "How is local model compute estimated?"),
    ),
    SupportArticle(
        id="costs",
        title="Cost estimates",
        answer=(
            "The cost dashboard separates processing compute, projected storage across each "
            "document's retention period, Azure transactions, and the current monthly storage run "
            "rate. These values use configured retail-rate assumptions and are estimates, not billed "
            "charges. Azure Cost Management remains the billing source."
        ),
        keywords=("cost", "price", "pricing", "charge", "billing", "bill", "estimate", "monthly", "expensive", "spend", "per customer"),
        href="/#cost-dashboard",
        link_label="Open cost dashboard",
        suggestions=("What is included in processing cost?", "How much does storage cost?", "Are these billed Azure charges?"),
    ),
    SupportArticle(
        id="privacy",
        title="Privacy and isolation",
        answer=(
            "PDF extraction, OCR, and selected Ollama analysis run inside the local Docker project; Papertrail "
            "does not send document text to a third-party LLM. When Azure storage is configured, "
            "source PDFs and JSON results are written to private, customer-specific containers."
        ),
        keywords=("private", "privacy", "secure", "security", "data", "third party", "leave", "local", "confidential", "customer see", "access"),
        href="/technology",
        link_label="View runtime boundaries",
        suggestions=("Where are files stored?", "Can customers see each other?", "Which AI models run locally?"),
    ),
    SupportArticle(
        id="troubleshooting",
        title="Basic troubleshooting",
        answer=(
            "Confirm the file is a valid, unencrypted PDF within the 50 MB and 500-page limits. "
            "Refresh history to check durable status, and try one model if local AI is busy. If the "
            "same run remains failed or queued, give the portal administrator its job ID and filename."
        ),
        keywords=("error", "failed", "not working", "stuck", "taking long", "slow", "rejected", "cannot", "can't", "problem", "troubleshoot", "queued"),
        href="/",
        link_label="Return to processor",
        suggestions=("Why was my PDF rejected?", "Where can I check run status?", "What file limits apply?"),
    ),
)

_STOP_WORDS = {
    "a", "about", "an", "and", "are", "can", "do", "does", "for", "how", "i",
    "in", "is", "it", "me", "my", "of", "on", "the", "this", "to", "what",
    "where", "why", "with",
}
_FALLBACK_SUGGESTIONS = (
    "How do I process a PDF?",
    "How are costs calculated?",
    "How do I change retention?",
    "Are my documents private?",
)


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9.]+", value.lower()))


def _terms(value: str) -> set[str]:
    return {term for term in _normalize(value).split() if term not in _STOP_WORDS}


def _score(article: SupportArticle, question: str, question_terms: set[str]) -> int:
    score = 0
    normalized_question = _normalize(question)
    for keyword in article.keywords:
        normalized_keyword = _normalize(keyword)
        if normalized_keyword in normalized_question:
            score += 4 + len(normalized_keyword.split())
        else:
            score += len(_terms(keyword) & question_terms)
    return score


def answer_support_question(question: str) -> dict[str, object]:
    """Return a grounded Level 1 response for a portal question."""
    clean_question = question.strip()
    question_terms = _terms(clean_question)
    if not question_terms or question_terms <= {"hello", "hi", "hey"}:
        article = ARTICLES[0]
    else:
        scored = sorted(
            ((_score(article, clean_question, question_terms), article) for article in ARTICLES),
            key=lambda item: item[0],
            reverse=True,
        )
        best_score, article = scored[0]
        if best_score < 4:
            return {
                "level": "level_1",
                "topic": "unknown",
                "title": "I need a little more detail",
                "answer": (
                    "I can answer Level 1 questions about uploads, processing, models, results, "
                    "customers, Azure storage, retention, costs, history, and privacy. For account "
                    "access, billing disputes, policy exceptions, or incidents, contact your portal administrator."
                ),
                "matched": False,
                "escalate": True,
                "suggestions": list(_FALLBACK_SUGGESTIONS),
                "links": [],
            }

    return {
        "level": "level_1",
        "topic": article.id,
        "title": article.title,
        "answer": article.answer,
        "matched": True,
        "escalate": False,
        "suggestions": list(article.suggestions),
        "links": [{"label": article.link_label, "href": article.href}],
    }