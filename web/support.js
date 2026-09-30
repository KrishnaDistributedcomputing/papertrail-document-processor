const supportHistoryKey = "papertrail.support-history";
const defaultSupportPrompts = [
  "How do I process a PDF?",
  "How are costs calculated?",
  "How do I change retention?",
  "Are my documents private?",
];

const supportState = {
  messages: readSupportHistory(),
  prompts: defaultSupportPrompts,
  sending: false,
};

function supportEscapeHtml(value) {
  const container = document.createElement("div");
  container.textContent = String(value ?? "");
  return container.innerHTML;
}

function supportSafeHref(value) {
  const href = String(value || "");
  return /^\/(?!\/)/.test(href) ? href : "/";
}

function readSupportHistory() {
  try {
    const history = JSON.parse(sessionStorage.getItem(supportHistoryKey));
    return Array.isArray(history) ? history.slice(-20) : [];
  } catch {
    return [];
  }
}

function storeSupportHistory() {
  sessionStorage.setItem(supportHistoryKey, JSON.stringify(supportState.messages.slice(-20)));
}

document.body.insertAdjacentHTML("beforeend", `
  <aside class="support-assistant" aria-label="Papertrail Level 1 support">
    <button id="support-launcher" class="support-launcher" type="button" aria-label="Open portal help" aria-expanded="false" aria-controls="support-panel">
      <span aria-hidden="true">?</span><strong>Portal help</strong>
    </button>
    <section id="support-panel" class="support-panel" role="dialog" aria-modal="false" aria-labelledby="support-title" hidden>
      <header class="support-header">
        <div><span>Level 1 support</span><h2 id="support-title">Ask Papertrail</h2></div>
        <div class="support-header-actions">
          <button id="support-clear" type="button" title="Clear conversation" aria-label="Clear conversation">&#8634;</button>
          <button id="support-close" type="button" title="Close support" aria-label="Close support">&times;</button>
        </div>
      </header>
      <div id="support-transcript" class="support-transcript" role="log" aria-live="polite" aria-relevant="additions"></div>
      <div id="support-prompts" class="support-prompts" aria-label="Suggested questions"></div>
      <form id="support-form" class="support-form">
        <label class="sr-only" for="support-question">Ask a question about the Papertrail portal</label>
        <input id="support-question" name="question" type="text" maxlength="500" autocomplete="off" placeholder="Ask about uploads, costs, storage..." required />
        <button type="submit" aria-label="Send question"><span>Send</span><b aria-hidden="true">&#8594;</b></button>
      </form>
      <p id="support-status" class="support-status" aria-live="polite"></p>
    </section>
  </aside>
`);

const supportLauncher = document.querySelector("#support-launcher");
const supportPanel = document.querySelector("#support-panel");
const supportTranscript = document.querySelector("#support-transcript");
const supportPrompts = document.querySelector("#support-prompts");
const supportForm = document.querySelector("#support-form");
const supportQuestion = document.querySelector("#support-question");
const supportStatus = document.querySelector("#support-status");

function supportWelcomeMessage() {
  return {
    role: "assistant",
    title: "Level 1 portal support",
    text: "Ask me about processing PDFs, local AI models, results, customer workspaces, Azure storage, retention, costs, history, or privacy.",
    links: [],
  };
}

function renderSupportMessages() {
  const messages = supportState.messages.length
    ? supportState.messages
    : [supportWelcomeMessage()];
  supportTranscript.innerHTML = messages.map((message) => `
    <article class="support-message ${message.role === "user" ? "user" : "assistant"}">
      <span>${message.role === "user" ? "You" : "Papertrail"}</span>
      ${message.title ? `<strong>${supportEscapeHtml(message.title)}</strong>` : ""}
      <p>${supportEscapeHtml(message.text)}</p>
      ${(message.links || []).map((link) => `<a href="${supportEscapeHtml(supportSafeHref(link.href))}">${supportEscapeHtml(link.label)} <span aria-hidden="true">&#8594;</span></a>`).join("")}
    </article>
  `).join("");
  supportTranscript.scrollTop = supportTranscript.scrollHeight;
}

function renderSupportPrompts() {
  supportPrompts.innerHTML = supportState.prompts.slice(0, 4).map((prompt) => `
    <button type="button" data-support-prompt="${supportEscapeHtml(prompt)}">${supportEscapeHtml(prompt)}</button>
  `).join("");
}

function setSupportOpen(open) {
  supportPanel.hidden = !open;
  supportLauncher.setAttribute("aria-expanded", String(open));
  supportLauncher.hidden = open;
  if (open) {
    renderSupportMessages();
    renderSupportPrompts();
    supportQuestion.focus();
  } else {
    supportLauncher.hidden = false;
    supportLauncher.focus();
  }
}

function addSupportMessage(message) {
  if (!supportState.messages.length && message.role === "user") {
    supportState.messages.push(supportWelcomeMessage());
  }
  supportState.messages.push(message);
  supportState.messages = supportState.messages.slice(-20);
  storeSupportHistory();
  renderSupportMessages();
}

async function askPortalSupport(question) {
  if (supportState.sending) return;
  supportState.sending = true;
  supportForm.querySelector("button").disabled = true;
  supportQuestion.disabled = true;
  supportStatus.textContent = "Finding the best portal answer...";
  addSupportMessage({ role: "user", text: question, links: [] });

  try {
    const response = await fetch("/api/v1/support/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    if (!response.ok) throw new Error("Portal support could not answer right now.");
    const answer = await response.json();
    addSupportMessage({
      role: "assistant",
      title: answer.title,
      text: answer.answer,
      links: answer.links || [],
    });
    supportState.prompts = answer.suggestions || defaultSupportPrompts;
    renderSupportPrompts();
    supportStatus.textContent = answer.escalate
      ? "This question may need a portal administrator."
      : "Answered from the Papertrail support guide.";
  } catch (error) {
    addSupportMessage({
      role: "assistant",
      title: "Support is temporarily unavailable",
      text: "Refresh the portal and try again. If the problem continues, contact the portal administrator.",
      links: [],
    });
    supportStatus.textContent = error.message;
  } finally {
    supportState.sending = false;
    supportForm.querySelector("button").disabled = false;
    supportQuestion.disabled = false;
    supportQuestion.value = "";
    supportQuestion.focus();
  }
}

supportLauncher.addEventListener("click", () => setSupportOpen(true));
document.querySelector("#support-close").addEventListener("click", () => setSupportOpen(false));
document.querySelector("#support-clear").addEventListener("click", () => {
  supportState.messages = [];
  supportState.prompts = defaultSupportPrompts;
  sessionStorage.removeItem(supportHistoryKey);
  supportStatus.textContent = "Conversation cleared.";
  renderSupportMessages();
  renderSupportPrompts();
  supportQuestion.focus();
});
supportPrompts.addEventListener("click", (event) => {
  const button = event.target.closest("[data-support-prompt]");
  if (button) askPortalSupport(button.dataset.supportPrompt);
});
supportForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = supportQuestion.value.trim();
  if (question) askPortalSupport(question);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !supportPanel.hidden) setSupportOpen(false);
});

renderSupportMessages();
renderSupportPrompts();