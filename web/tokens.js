const customerFilter = document.querySelector("#token-customer-filter");
const refreshButton = document.querySelector("#refresh-tokens");
const statusElement = document.querySelector("#token-status");
const liveRegion = document.querySelector("#live-region");

const state = {
  customers: [],
  selectedCustomer: "all",
};

function formatNumber(value) {
  return Number(value || 0).toLocaleString();
}

function formatCurrency(value) {
  const amount = Number(value || 0);
  const precision = amount > 0 && amount < 0.01 ? 6 : 2;
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  }).format(amount);
}

function formatRuntime(value) {
  const milliseconds = Number(value || 0);
  if (milliseconds < 60_000) return `${(milliseconds / 1000).toFixed(1)} sec`;
  const minutes = Math.floor(milliseconds / 60_000);
  const seconds = Math.round((milliseconds % 60_000) / 1000);
  return `${minutes} min ${seconds} sec`;
}

function formatCompletedAt(value) {
  if (!value) return "Unavailable";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function escapeHtml(value) {
  const container = document.createElement("div");
  container.textContent = String(value ?? "");
  return container.innerHTML;
}

function customerClass(value) {
  return /^[a-z0-9-]+$/.test(String(value)) ? `customer-${value}` : "customer-default";
}

function renderCustomerFilter() {
  customerFilter.innerHTML = [
    '<option value="all">All customers</option>',
    ...state.customers.map((customer) => (
      `<option value="${escapeHtml(customer.id)}">${escapeHtml(customer.name)}</option>`
    )),
  ].join("");
  customerFilter.value = state.selectedCustomer;
  customerFilter.disabled = false;
}

function renderKpis(totals) {
  document.querySelector("#token-kpis").innerHTML = `
    <div><dt>Total tokens</dt><dd>${formatNumber(totals.total_tokens)}</dd></div>
    <div><dt>Prompt tokens</dt><dd>${formatNumber(totals.prompt_tokens)}</dd></div>
    <div><dt>Output tokens</dt><dd>${formatNumber(totals.output_tokens)}</dd></div>
    <div><dt>Model calls</dt><dd>${formatNumber(totals.model_calls)}</dd></div>
    <div><dt>Azure AI what-if</dt><dd>${formatCurrency(totals.illustrative_azure_ai_cost_usd)}</dd></div>
    <div><dt>Local model compute</dt><dd>${formatCurrency(totals.estimated_compute_cost_usd)}</dd></div>
  `;
}

function renderSummaryTable(target, entries, identityLabel) {
  const maximumTokens = Math.max(...entries.map((entry) => Number(entry.total_tokens || 0)), 1);
  target.innerHTML = entries.length
    ? entries.map((entry) => `
      <tr class="${identityLabel === "Customer" ? customerClass(entry.id) : ""}">
        <th scope="row">
          <span class="token-identity">${identityLabel === "Customer" ? "<i></i>" : ""}<strong>${escapeHtml(entry.name)}</strong></span>
          <small>${formatNumber(entry.prompt_tokens)} prompt + ${formatNumber(entry.output_tokens)} output</small>
        </th>
        <td>${formatNumber(identityLabel === "Customer" ? entry.documents : entry.calls)}</td>
        <td class="token-volume">
          <strong>${formatNumber(entry.total_tokens)}</strong>
          <progress max="${maximumTokens}" value="${Number(entry.total_tokens || 0)}" aria-label="${escapeHtml(entry.name)}: ${formatNumber(entry.total_tokens)} tokens"></progress>
        </td>
        <td>${formatRuntime(entry.runtime_ms)}</td>
        <td>${formatCurrency(entry.illustrative_azure_ai_cost_usd)}</td>
        <td>${formatCurrency(entry.estimated_compute_cost_usd)}</td>
      </tr>
    `).join("")
    : '<tr><td colspan="6" class="token-empty">No completed model telemetry in this scope.</td></tr>';
}

function renderRecentCalls(calls) {
  document.querySelector("#recent-token-body").innerHTML = calls.length
    ? calls.map((call) => `
      <tr>
        <td>${escapeHtml(formatCompletedAt(call.completed_at))}</td>
        <td><span class="token-identity ${customerClass(call.customer_id)}"><i></i><strong>${escapeHtml(call.customer_name)}</strong></span></td>
        <th scope="row" title="${escapeHtml(call.filename)}">${escapeHtml(call.filename)}</th>
        <td>${escapeHtml(call.model_name)}</td>
        <td>${formatNumber(call.prompt_tokens)}</td>
        <td>${formatNumber(call.output_tokens)}</td>
        <td><strong>${formatNumber(call.total_tokens)}</strong></td>
        <td>${formatRuntime(call.runtime_ms)}</td>
        <td>${formatCurrency(call.illustrative_azure_ai_cost_usd)}</td>
        <td>${formatCurrency(call.estimated_compute_cost_usd)}</td>
      </tr>
    `).join("")
    : '<tr><td colspan="10" class="token-empty">No completed model calls in this scope.</td></tr>';
}

function renderMethodology(payload) {
  const { pricing, totals, methodology } = payload;
  const runtimeHours = Number(totals.runtime_ms || 0) / 3_600_000;
  document.querySelector("#token-formula").innerHTML = `
    <div>
      <span>Illustrative Azure AI tokens</span>
      <strong>${formatNumber(totals.prompt_tokens)} input &times; ${formatCurrency(pricing.azure_sample_input_1m_tokens_usd)} / 1M + ${formatNumber(totals.output_tokens)} output &times; ${formatCurrency(pricing.azure_sample_output_1m_tokens_usd)} / 1M</strong>
      <b>= ${formatCurrency(totals.illustrative_azure_ai_cost_usd)} Azure what-if</b>
    </div>
    <div>
      <span>Recorded local model runtime</span>
      <strong>${runtimeHours.toFixed(4)} hours &times; ${formatCurrency(pricing.effective_compute_hour_usd)} / hour</strong>
      <b>= ${formatCurrency(totals.estimated_compute_cost_usd)} local compute</b>
    </div>
  `;
  document.querySelector("#local-token-rate").textContent = `${formatCurrency(pricing.input_1m_tokens_usd)} / 1M`;
  document.querySelector("#azure-input-token-rate").textContent = `${formatCurrency(pricing.azure_sample_input_1m_tokens_usd)} / 1M`;
  document.querySelector("#azure-output-token-rate").textContent = `${formatCurrency(pricing.azure_sample_output_1m_tokens_usd)} / 1M`;
  document.querySelector("#vcpu-rate").textContent = `${formatCurrency(pricing.vcpu_hour_usd)} / hour`;
  document.querySelector("#memory-rate").textContent = `${pricing.memory_gb} GB × ${formatCurrency(pricing.memory_gb_hour_usd)} / GB-hour`;
  document.querySelector("#effective-rate").textContent = `${formatCurrency(pricing.effective_compute_hour_usd)} / hour`;
  document.querySelector("#token-method-note").textContent = `${methodology.coverage} ${methodology.azure_sample} ${methodology.cost_boundary}`;
}

function renderOverview(payload) {
  const { totals } = payload;
  renderKpis(totals);
  renderSummaryTable(document.querySelector("#model-usage-body"), payload.models || [], "Model");
  renderSummaryTable(document.querySelector("#customer-usage-body"), payload.customers || [], "Customer");
  renderRecentCalls(payload.recent_calls || []);
  renderMethodology(payload);

  document.querySelector("#token-charge").textContent = formatCurrency(totals.metered_token_cost_usd);
  document.querySelector("#azure-ai-cost").textContent = formatCurrency(totals.illustrative_azure_ai_cost_usd);
  document.querySelector("#token-compute").textContent = formatCurrency(totals.estimated_compute_cost_usd);
  document.querySelector("#token-charge-copy").textContent = `Local Ollama input and output rates are both ${formatCurrency(0)} per 1 million tokens.`;
  document.querySelector("#azure-ai-cost-copy").textContent = `${formatNumber(totals.prompt_tokens)} prompt and ${formatNumber(totals.output_tokens)} output tokens at sample rates of ${formatCurrency(payload.pricing.azure_sample_input_1m_tokens_usd)} and ${formatCurrency(payload.pricing.azure_sample_output_1m_tokens_usd)} per 1 million.`;
  document.querySelector("#token-compute-copy").textContent = `${formatRuntime(totals.runtime_ms)} of recorded model runtime at ${formatCurrency(payload.pricing.effective_compute_hour_usd)} per hour.`;

  const selected = state.customers.find((customer) => customer.id === state.selectedCustomer);
  document.querySelector("#token-scope-label").textContent = selected?.name || "All customers";
  document.querySelector("#token-coverage").textContent = `${formatNumber(totals.calls_with_token_telemetry)} of ${formatNumber(totals.model_calls)} completed model calls include token telemetry across ${formatNumber(totals.documents_with_token_telemetry)} of ${formatNumber(totals.completed_documents)} completed documents.`;
}

async function loadCustomers() {
  const response = await fetch("/api/v1/customers");
  if (!response.ok) throw new Error("Customer workspaces could not be loaded.");
  const payload = await response.json();
  state.customers = payload.customers || [];
  const requestedCustomer = new URLSearchParams(window.location.search).get("customer_id");
  if (requestedCustomer && state.customers.some((customer) => customer.id === requestedCustomer)) {
    state.selectedCustomer = requestedCustomer;
  }
  renderCustomerFilter();
}

async function loadTokenUsage() {
  refreshButton.disabled = true;
  customerFilter.disabled = true;
  statusElement.textContent = "Calculating";
  statusElement.dataset.status = "pending";
  try {
    const query = state.selectedCustomer === "all"
      ? ""
      : `?customer_id=${encodeURIComponent(state.selectedCustomer)}`;
    const response = await fetch(`/api/v1/tokens/overview${query}`);
    if (!response.ok) throw new Error("Token usage could not be loaded.");
    renderOverview(await response.json());
    statusElement.textContent = "Current";
    statusElement.dataset.status = "connected";
    liveRegion.textContent = "Token usage updated.";
  } catch (error) {
    statusElement.textContent = "Unavailable";
    statusElement.dataset.status = "degraded";
    liveRegion.textContent = error.message;
  } finally {
    refreshButton.disabled = false;
    customerFilter.disabled = state.customers.length === 0;
  }
}

customerFilter.addEventListener("change", () => {
  state.selectedCustomer = customerFilter.value;
  loadTokenUsage();
});
refreshButton.addEventListener("click", loadTokenUsage);

async function initialize() {
  try {
    await loadCustomers();
  } catch (error) {
    liveRegion.textContent = error.message;
  }
  await loadTokenUsage();
}

initialize();