const views = {
  upload: document.querySelector("#upload-view"),
  processing: document.querySelector("#processing-view"),
  result: document.querySelector("#result-view"),
};
const fileInput = document.querySelector("#file-input");
const dropZone = document.querySelector("#drop-zone");
const fileList = document.querySelector("#file-list");
const selectedFiles = document.querySelector("#selected-files");
const submitButton = document.querySelector("#submit-button");
const errorMessage = document.querySelector("#upload-error");
const modelOptions = document.querySelector("#model-options");
const customerSelect = document.querySelector("#customer-select");
const costCustomerFilter = document.querySelector("#cost-customer-filter");
const storageCustomerList = document.querySelector("#storage-customer-list");
const liveRegion = document.querySelector("#live-region");
const activeJobsStorageKey = "papertrail.active-jobs";
const jobLabelsStorageKey = "papertrail.job-labels";
const retentionPresets = [
  [7, "7 days"],
  [30, "30 days"],
  [60, "60 days"],
  [90, "90 days"],
  [180, "180 days"],
  [365, "365 days (1 year)"],
  [730, "730 days (2 years)"],
  [1825, "1,825 days (5 years)"],
  [2555, "2,555 days (7 years)"],
  [3650, "3,650 days (10 years)"],
];
const state = {
  results: [],
  result: null,
  selectedFiles: [],
  jobs: [],
  history: [],
  availableModels: [],
  selectedModels: [],
  maxSelectedModels: 1,
  customers: [],
  selectedCustomer: "microsoft",
  costOverview: null,
  costCustomer: "all",
  costDetailCustomer: null,
  storageOverview: null,
  page: 1,
  tab: "content",
  query: "",
};

function showView(name) {
  Object.entries(views).forEach(([key, element]) => { element.hidden = key !== name; });
}

function announce(message) {
  liveRegion.textContent = message;
}

function formatBytes(bytes) {
  if (!bytes) return "0 bytes";
  const units = ["bytes", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function formatCurrency(value) {
  const amount = Number(value || 0);
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: amount > 0 && amount < 0.01 ? 6 : 2,
    maximumFractionDigits: 6,
  }).format(amount);
}

function formatCategory(value) {
  return String(value || "not classified")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatHistoryTime(value) {
  if (!value) return "Time unavailable";
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

function readJobLabels() {
  try {
    return JSON.parse(sessionStorage.getItem(jobLabelsStorageKey)) || {};
  } catch {
    return {};
  }
}

function readActiveJobs() {
  try {
    const jobs = JSON.parse(sessionStorage.getItem(activeJobsStorageKey));
    return Array.isArray(jobs)
      ? jobs.filter((job) => job?.job_id && job?.document_id)
      : [];
  } catch {
    return [];
  }
}

function storeJobLabels(jobs) {
  sessionStorage.setItem(jobLabelsStorageKey, JSON.stringify(Object.fromEntries(
    jobs.filter((job) => job.job_id).map((job) => [job.job_id, job.filename]),
  )));
}

function storeActiveJobs(jobs) {
  const activeJobs = jobs
    .filter((job) => job.job_id && job.document_id)
    .map(({ job_id, document_id, filename }) => ({ job_id, document_id, filename }));
  sessionStorage.setItem(activeJobsStorageKey, JSON.stringify(activeJobs));
}

function renderSelectedFiles() {
  const count = state.selectedFiles.length;
  fileList.hidden = count === 0;
  dropZone.classList.toggle("compact", count > 0);
  submitButton.disabled = count === 0 || state.selectedModels.length === 0 || state.customers.length === 0;
  document.querySelector("#file-count").textContent = `${count} document${count === 1 ? "" : "s"} selected`;
  document.querySelector("#submit-label").textContent = count
    ? `Process ${count} document${count === 1 ? "" : "s"}`
    : "Process documents";
  selectedFiles.innerHTML = state.selectedFiles.map((file, index) => `
    <div class="selected-file">
      <span class="file-glyph" aria-hidden="true">PDF</span>
      <span><strong>${escapeHtml(file.name)}</strong><small>${formatBytes(file.size)}</small></span>
      <button class="icon-button" type="button" data-remove-index="${index}" title="Remove file" aria-label="Remove ${escapeHtml(file.name)}">&times;</button>
    </div>
  `).join("");
}

function selectedCustomer() {
  return state.customers.find((customer) => customer.id === state.selectedCustomer);
}

function renderCustomerPicker() {
  customerSelect.innerHTML = state.customers.map((customer) => `
    <option value="${escapeHtml(customer.id)}" ${customer.id === state.selectedCustomer ? "selected" : ""}>${escapeHtml(customer.name)} sample workspace</option>
  `).join("");
  customerSelect.disabled = state.customers.length === 0;
  const customer = selectedCustomer();
  document.querySelector("#customer-destination").textContent = customer
    ? `${customer.container} · ${customer.retention_days} day retention`
    : "Choose where this batch will be stored.";
  renderSelectedFiles();
}

async function loadCustomers() {
  const response = await fetch("/api/v1/customers");
  if (!response.ok) throw new Error("Customer workspaces could not be loaded.");
  const payload = await response.json();
  state.customers = payload.customers || [];
  if (!state.customers.some((customer) => customer.id === state.selectedCustomer)) {
    state.selectedCustomer = state.customers[0]?.id || "";
  }
  renderCustomerPicker();
}

function renderModels() {
  modelOptions.innerHTML = state.availableModels.map((model) => `
    <label class="model-option">
      <input type="checkbox" name="analysis-model" value="${escapeHtml(model.id)}" ${state.selectedModels.includes(model.id) ? "checked" : ""} />
      <span class="model-option-copy">
        <strong>${escapeHtml(model.name)}</strong>
        <small>${escapeHtml(model.description)}</small>
      </span>
      <span class="model-size">${escapeHtml(model.size)}</span>
    </label>
  `).join("");
  renderSelectedFiles();
}

async function loadModels() {
  try {
    const response = await fetch("/api/v1/models");
    if (!response.ok) throw new Error("Local models could not be loaded.");
    const payload = await response.json();
    state.availableModels = payload.models || [];
    state.maxSelectedModels = payload.max_selected || 1;
    state.selectedModels = state.availableModels.filter((model) => model.default).map((model) => model.id);
    if (!state.selectedModels.length && state.availableModels.length) {
      state.selectedModels = [state.availableModels[0].id];
    }
    renderModels();
  } catch (error) {
    modelOptions.innerHTML = `<span class="model-loading error-message">${escapeHtml(error.message)}</span>`;
    state.selectedModels = [];
    renderSelectedFiles();
  }
}

modelOptions.addEventListener("change", (event) => {
  const selected = [...modelOptions.querySelectorAll('input[type="checkbox"]:checked')]
    .map((input) => input.value);
  if (selected.length > state.maxSelectedModels) {
    event.target.checked = false;
    errorMessage.textContent = `Choose at most ${state.maxSelectedModels} analysis models.`;
    return;
  }
  errorMessage.textContent = "";
  state.selectedModels = selected;
  document.querySelector("#model-picker-help").textContent = selected.length > 1
    ? `${selected.length} models will analyze the same extracted text for comparison.`
    : "Select one model, or up to two to compare results.";
  renderSelectedFiles();
});

function renderHistory() {
  const historyStatus = document.querySelector("#history-status");
  const historyList = document.querySelector("#history-list");
  historyStatus.hidden = state.history.length > 0;
  historyStatus.textContent = "No saved processing runs yet.";
  historyList.innerHTML = state.history.map((run) => {
    const canOpen = run.status === "completed" || ["queued", "processing"].includes(run.status);
    const stateLabel = run.status === "processing" ? run.stage : run.status;
    const detail = run.page_count
      ? `${run.page_count} page${run.page_count === 1 ? "" : "s"}`
      : `Last stage: ${run.stage}`;
    const aiLabel = run.analysis_status
      ? `AI ${run.analysis_status}${run.analysis_model ? ` · ${run.analysis_model}` : ""}`
      : "AI pending";
    return `
      <button class="history-item" type="button" data-history-job="${escapeHtml(run.job_id)}" ${canOpen ? "" : "disabled"}>
        <span class="history-name"><strong>${escapeHtml(run.filename)}</strong><small>${escapeHtml(detail)}</small></span>
        <span class="history-state">${escapeHtml(stateLabel)}</span>
        <span class="history-category">${escapeHtml(formatCategory(run.category || "unclassified"))}</span>
        <span><span class="history-ai">${escapeHtml(aiLabel)}</span><span class="history-time">${escapeHtml(formatHistoryTime(run.completed_at || run.updated_at))}</span></span>
      </button>
    `;
  }).join("");
}

async function loadHistory() {
  const historyStatus = document.querySelector("#history-status");
  historyStatus.hidden = false;
  historyStatus.textContent = "Loading saved runs...";
  try {
    const customerQuery = state.selectedCustomer
      ? `&customer_id=${encodeURIComponent(state.selectedCustomer)}`
      : "";
    const response = await fetch(`/api/v1/history?limit=20${customerQuery}`);
    if (!response.ok) throw new Error("History could not be loaded.");
    const payload = await response.json();
    state.history = payload.runs || [];
    renderHistory();
  } catch (error) {
    historyStatus.textContent = error.message;
  }
}

function customerClass(value) {
  return /^[a-z0-9-]+$/.test(String(value)) ? `customer-${value}` : "customer-default";
}

function renderRetentionOptions(retentionDays) {
  const selectedDays = Number(retentionDays);
  const options = retentionPresets.some(([days]) => days === selectedDays)
    ? retentionPresets
    : [...retentionPresets, [selectedDays, `${selectedDays.toLocaleString()} days (current)`]]
      .sort(([left], [right]) => left - right);
  return options.map(([days, label]) => `
    <option value="${days}" ${days === selectedDays ? "selected" : ""}>${label}</option>
  `).join("");
}

function summarizeCosts(customers) {
  return customers.reduce((totals, customer) => ({
    documents: totals.documents + Number(customer.document_count || 0),
    compute_usd: totals.compute_usd + Number(customer.compute_usd || 0),
    storage_for_retention_usd: totals.storage_for_retention_usd + Number(customer.storage_for_retention_usd || 0),
    transactions_usd: totals.transactions_usd + Number(customer.transactions_usd || 0),
    estimated_total_usd: totals.estimated_total_usd + Number(customer.estimated_total_usd || 0),
    monthly_storage_cost_usd: totals.monthly_storage_cost_usd + Number(customer.monthly_storage_cost_usd || 0),
  }), {
    documents: 0,
    compute_usd: 0,
    storage_for_retention_usd: 0,
    transactions_usd: 0,
    estimated_total_usd: 0,
    monthly_storage_cost_usd: 0,
  });
}

function formatRuntime(milliseconds) {
  const seconds = Math.max(0, Number(milliseconds || 0)) / 1000;
  return seconds < 60
    ? `${seconds.toFixed(1)} seconds`
    : `${(seconds / 60).toFixed(1)} minutes`;
}

function renderCustomerCostDetail(customer) {
  return `
    <header>
      <div><span>Customer costing</span><h4>${escapeHtml(customer.name)}</h4><small>${escapeHtml(customer.container)}</small></div>
      <button type="button" data-close-cost-detail title="Close costing" aria-label="Close ${escapeHtml(customer.name)} costing">&times;</button>
    </header>
    <div class="customer-cost-equation" aria-label="${escapeHtml(customer.name)} cost calculation">
      <div><span>Processing</span><strong>${formatCurrency(customer.compute_usd)}</strong></div>
      <b aria-hidden="true">+</b>
      <div><span>Retention storage</span><strong>${formatCurrency(customer.storage_for_retention_usd)}</strong></div>
      <b aria-hidden="true">+</b>
      <div><span>Transactions</span><strong>${formatCurrency(customer.transactions_usd)}</strong></div>
      <b aria-hidden="true">=</b>
      <div class="customer-cost-equation-total"><span>Estimated total</span><strong>${formatCurrency(customer.estimated_total_usd)}</strong></div>
    </div>
    <dl class="customer-cost-facts">
      <div><dt>Completed documents</dt><dd>${Number(customer.document_count).toLocaleString()}</dd></div>
      <div><dt>Average / document</dt><dd>${formatCurrency(customer.cost_per_document_usd)}</dd></div>
      <div><dt>Measured runtime</dt><dd>${formatRuntime(customer.runtime_ms)}</dd></div>
      <div><dt>Stored data</dt><dd>${formatBytes(customer.storage_bytes)}</dd></div>
      <div><dt>Storage / month</dt><dd>${formatCurrency(customer.monthly_storage_cost_usd)}</dd></div>
      <div><dt>Portfolio share</dt><dd>${Number(customer.cost_share_percent || 0).toFixed(1)}%</dd></div>
    </dl>
    <p>Monthly storage is a current run rate and is shown separately; it is not added again to the estimated total. Inventory source: ${escapeHtml(customer.inventory_status.replaceAll("_", " "))}.</p>
  `;
}

function renderCostDashboard() {
  const overview = state.costOverview;
  if (!overview) return;
  const allCustomers = overview.customers || [];
  const visibleCustomers = state.costCustomer === "all"
    ? allCustomers
    : allCustomers.filter((customer) => customer.id === state.costCustomer);
  const totals = summarizeCosts(visibleCustomers);
  const averageCost = totals.documents
    ? totals.estimated_total_usd / totals.documents
    : 0;
  const costStatus = document.querySelector("#cost-status");
  costStatus.textContent = overview.warnings?.length ? "Estimate degraded" : "Retail estimate";
  costStatus.dataset.status = overview.warnings?.length ? "degraded" : "connected";

  document.querySelector("#cost-kpis").innerHTML = `
    <div><dt>Completed documents</dt><dd>${totals.documents.toLocaleString()}</dd></div>
    <div><dt>Estimated total</dt><dd>${formatCurrency(totals.estimated_total_usd)}</dd></div>
    <div><dt>Processing</dt><dd>${formatCurrency(totals.compute_usd)}</dd></div>
    <div><dt>Retention storage</dt><dd>${formatCurrency(totals.storage_for_retention_usd)}</dd></div>
    <div><dt>Transactions</dt><dd>${formatCurrency(totals.transactions_usd)}</dd></div>
    <div><dt>Storage / month</dt><dd>${formatCurrency(totals.monthly_storage_cost_usd)}</dd></div>
  `;

  const componentTotal = Math.max(
    totals.compute_usd + totals.storage_for_retention_usd + totals.transactions_usd,
    0.000001,
  );
  const components = [
    ["compute", "Processing compute", totals.compute_usd],
    ["storage", "Retention storage", totals.storage_for_retention_usd],
    ["transactions", "Azure transactions", totals.transactions_usd],
  ];
  document.querySelector("#cost-composition").innerHTML = components.map(([key, label, value]) => `
    <div class="cost-component component-${key}">
      <div><strong>${label}</strong><span>${formatCurrency(value)}</span></div>
      <progress max="${componentTotal}" value="${value}" aria-label="${label}: ${formatCurrency(value)}"></progress>
      <small>${componentTotal > 0 ? ((value / componentTotal) * 100).toFixed(1) : "0.0"}% of classified cost</small>
    </div>
  `).join("");

  const rankedCustomers = [...visibleCustomers].sort(
    (left, right) => Number(right.estimated_total_usd) - Number(left.estimated_total_usd),
  );
  const maximumCustomerCost = Math.max(
    ...rankedCustomers.map((customer) => Number(customer.estimated_total_usd || 0)),
    0.000001,
  );
  if (!rankedCustomers.some((customer) => customer.id === state.costDetailCustomer)) {
    state.costDetailCustomer = null;
  }
  const rankingMarkup = rankedCustomers.map((customer) => {
    const selected = customer.id === state.costDetailCustomer;
    return `
      <button class="customer-cost-bar ${customerClass(customer.id)}" type="button" data-cost-customer="${escapeHtml(customer.id)}" aria-expanded="${selected}" aria-controls="customer-cost-detail">
        <div class="customer-cost-label">
          <span><i></i><strong>${escapeHtml(customer.name)}</strong></span>
          <span class="customer-cost-total"><b>${formatCurrency(customer.estimated_total_usd)}</b><em aria-hidden="true">&#8250;</em></span>
        </div>
        <progress max="${maximumCustomerCost}" value="${Number(customer.estimated_total_usd || 0)}" aria-label="${escapeHtml(customer.name)} estimated total ${formatCurrency(customer.estimated_total_usd)}"></progress>
        <small>${customer.document_count} document${customer.document_count === 1 ? "" : "s"} · ${formatCurrency(customer.cost_per_document_usd)} average · ${Number(customer.cost_share_percent || 0).toFixed(1)}% of portfolio</small>
      </button>
      ${selected ? `<article id="customer-cost-detail" class="customer-cost-detail ${customerClass(customer.id)}" tabindex="-1" aria-live="polite">${renderCustomerCostDetail(customer)}</article>` : ""}
    `;
  }).join("");
  document.querySelector("#customer-cost-bars").innerHTML = rankingMarkup
    + (state.costDetailCustomer ? "" : '<article id="customer-cost-detail" class="customer-cost-detail" tabindex="-1" aria-live="polite" hidden></article>');

  document.querySelector("#cost-table-body").innerHTML = rankedCustomers.map((customer) => `
    <tr>
      <th scope="row"><span class="cost-customer-key ${customerClass(customer.id)}"><i></i>${escapeHtml(customer.name)}</span><small>${escapeHtml(customer.container)}</small></th>
      <td>${Number(customer.document_count).toLocaleString()}</td>
      <td>${formatCurrency(customer.compute_usd)}</td>
      <td>${formatCurrency(customer.storage_for_retention_usd)}</td>
      <td>${formatCurrency(customer.transactions_usd)}</td>
      <td>${formatCurrency(customer.cost_per_document_usd)}</td>
      <td>${formatCurrency(customer.monthly_storage_cost_usd)}</td>
      <td><strong>${formatCurrency(customer.estimated_total_usd)}</strong></td>
    </tr>
  `).join("");

  const inventorySource = allCustomers.some((customer) => customer.inventory_status === "live")
    ? "live Azure container inventory"
    : "locally recorded stored bytes";
  document.querySelector("#cost-methodology").textContent = `Average cost per document: ${formatCurrency(averageCost)}. Processing and lifecycle storage are cumulative estimates for completed documents. The monthly run rate uses ${inventorySource} at ${formatCurrency(overview.pricing.storage_gb_month_usd)} per GB-month. ${overview.methodology.billing_source}`;
}

async function loadCostOverview() {
  const costStatus = document.querySelector("#cost-status");
  costStatus.textContent = "Calculating...";
  costStatus.dataset.status = "";
  try {
    const response = await fetch("/api/v1/costs/overview");
    if (!response.ok) throw new Error("Customer costs could not be loaded.");
    state.costOverview = await response.json();
    const availableCustomers = state.costOverview.customers || [];
    if (state.costCustomer !== "all" && !availableCustomers.some((customer) => customer.id === state.costCustomer)) {
      state.costCustomer = "all";
    }
    costCustomerFilter.innerHTML = `
      <option value="all">All customers</option>
      ${availableCustomers.map((customer) => `<option value="${escapeHtml(customer.id)}">${escapeHtml(customer.name)}</option>`).join("")}
    `;
    costCustomerFilter.value = state.costCustomer;
    costCustomerFilter.disabled = false;
    renderCostDashboard();
  } catch (error) {
    costStatus.textContent = "Unavailable";
    costStatus.dataset.status = "degraded";
    document.querySelector("#customer-cost-bars").innerHTML = `<p class="error-message">${escapeHtml(error.message)}</p>`;
  }
}

function renderStorageOverview() {
  const overview = state.storageOverview;
  if (!overview) return;
  const storage = overview.storage;
  const totals = overview.totals;
  const storageStatus = document.querySelector("#storage-status");
  const accessPending = !storage.configured && Boolean(storage.account);
  storageStatus.textContent = accessPending
    ? "app access pending"
    : storage.status.replaceAll("_", " ");
  storageStatus.dataset.status = accessPending ? "pending" : storage.status;
  document.querySelector("#storage-totals").innerHTML = `
    <div><dt>Customers</dt><dd>${totals.customers}</dd></div>
    <div><dt>Documents</dt><dd>${totals.documents}</dd></div>
    <div><dt>Stored data</dt><dd>${formatBytes(totals.bytes)}</dd></div>
    <div><dt>Estimated processing</dt><dd>${formatCurrency(totals.estimated_processing_cost_usd)}</dd></div>
    <div><dt>Monthly storage</dt><dd>${formatCurrency(totals.monthly_storage_cost_usd)}</dd></div>
  `;
  document.querySelector("#storage-account").innerHTML = `
    <span>Storage account</span>
    <strong>${escapeHtml(storage.account || "Not configured")}</strong>
    <small>${escapeHtml(storage.region)} · ${escapeHtml(storage.sku)} · ${escapeHtml(storage.retention_policy || "retention not configured")}</small>
    <b>${totals.blobs} blobs</b>
  `;
  const maximumBytes = Math.max(1, ...overview.customers.map((customer) => customer.bytes));
  storageCustomerList.innerHTML = overview.customers.map((customer) => `
      <article class="storage-customer-row ${customerClass(customer.id)}">
        <div class="storage-customer-name"><i></i><span><strong>${escapeHtml(customer.name)}</strong><small>${escapeHtml(customer.container)}</small></span></div>
        <div class="storage-usage">
          <progress max="${maximumBytes}" value="${customer.bytes}" aria-label="${escapeHtml(customer.name)} storage usage"></progress>
          <small>${customer.blob_count} blobs · ${formatBytes(customer.bytes)} · ${escapeHtml(customer.inventory_status.replaceAll("_", " "))}</small>
        </div>
        <div class="storage-cost"><small>Processing / storage month</small><strong>${formatCurrency(customer.estimated_processing_cost_usd)}</strong><span>${formatCurrency(customer.monthly_storage_cost_usd)} / mo</span></div>
        <label class="retention-control">
          <span>Azure lifecycle duration</span>
          <select data-retention-input="${escapeHtml(customer.id)}" aria-label="Azure lifecycle duration for ${escapeHtml(customer.name)}">
            ${renderRetentionOptions(customer.retention_days)}
          </select>
          <button type="button" data-save-retention="${escapeHtml(customer.id)}">Apply</button>
        </label>
      </article>
    `).join("");
  const accessNote = accessPending
    ? " Account provisioned; live inventory and cloud uploads require an approved Azure data-plane network path."
    : "";
  document.querySelector("#storage-pricing-note").textContent = `Hot LRS estimate: ${formatCurrency(overview.pricing.storage_gb_month_usd)} per GB-month. Processing totals include configured compute, storage, and transaction rates; Azure Cost Management remains the billing source.${accessNote}`;
}

async function loadStorageOverview() {
  try {
    const response = await fetch("/api/v1/storage/overview");
    if (!response.ok) throw new Error("Azure storage inventory could not be loaded.");
    state.storageOverview = await response.json();
    renderStorageOverview();
  } catch (error) {
    document.querySelector("#storage-status").textContent = "unavailable";
    storageCustomerList.innerHTML = `<p class="error-message">${escapeHtml(error.message)}</p>`;
  }
}

customerSelect.addEventListener("change", () => {
  state.selectedCustomer = customerSelect.value;
  renderCustomerPicker();
  loadHistory();
});

costCustomerFilter.addEventListener("change", () => {
  state.costCustomer = costCustomerFilter.value;
  renderCostDashboard();
});
document.querySelector(".customer-cost-ranking").addEventListener("click", (event) => {
  const closeButton = event.target.closest("[data-close-cost-detail]");
  if (closeButton) {
    state.costDetailCustomer = null;
    renderCostDashboard();
    return;
  }
  const customerButton = event.target.closest("[data-cost-customer]");
  if (!customerButton) return;
  state.costDetailCustomer = state.costDetailCustomer === customerButton.dataset.costCustomer
    ? null
    : customerButton.dataset.costCustomer;
  renderCostDashboard();
  if (state.costDetailCustomer) {
    document.querySelector("#customer-cost-detail").focus({ preventScroll: true });
  }
});
document.querySelector("#refresh-costs").addEventListener("click", loadCostOverview);
document.querySelector("#refresh-storage").addEventListener("click", loadStorageOverview);
storageCustomerList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-save-retention]");
  if (!button) return;
  const customerId = button.dataset.saveRetention;
  const select = storageCustomerList.querySelector(`[data-retention-input="${customerId}"]`);
  const retentionDays = Number(select?.value);
  if (!Number.isInteger(retentionDays) || retentionDays < 1 || retentionDays > 3650) {
    announce("Retention must be between 1 and 3650 days.");
    return;
  }
  button.disabled = true;
  button.textContent = "Saving";
  try {
    const response = await fetch(`/api/v1/customers/${encodeURIComponent(customerId)}/retention`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ retention_days: retentionDays }),
    });
    if (!response.ok) throw new Error("Retention could not be updated.");
    const updated = await response.json();
    const customer = state.customers.find((item) => item.id === customerId);
    if (customer) customer.retention_days = retentionDays;
    renderCustomerPicker();
    const message = updated.cloud_status === "updated"
      ? `${customer?.name || customerId} Azure lifecycle policy updated to ${retentionDays} days.`
      : `${customer?.name || customerId} duration saved locally; Azure policy update is ${updated.cloud_status.replaceAll("_", " ")}.`;
    announce(message);
    await loadStorageOverview();
  } catch (error) {
    button.disabled = false;
    button.textContent = "Apply";
    announce(error.message);
  }
});

function addFiles(files) {
  errorMessage.textContent = "";
  for (const file of files) {
    if (state.selectedFiles.length >= 10) {
      errorMessage.textContent = "A batch can contain at most 10 documents.";
      break;
    }
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      errorMessage.textContent = `${file.name} is not a PDF document.`;
      continue;
    }
    if (file.size > 50 * 1024 * 1024) {
      errorMessage.textContent = `${file.name} exceeds the 50 MB limit.`;
      continue;
    }
    const duplicate = state.selectedFiles.some((selected) => (
      selected.name === file.name && selected.size === file.size && selected.lastModified === file.lastModified
    ));
    if (!duplicate) state.selectedFiles.push(file);
  }
  renderSelectedFiles();
}

fileInput.addEventListener("change", () => {
  addFiles([...fileInput.files]);
  fileInput.value = "";
});
["dragenter", "dragover"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
  event.preventDefault();
  dropZone.classList.add("dragging");
}));
["dragleave", "drop"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragging");
}));
dropZone.addEventListener("drop", (event) => addFiles([...event.dataTransfer.files]));
selectedFiles.addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-index]");
  if (!button) return;
  state.selectedFiles.splice(Number(button.dataset.removeIndex), 1);
  renderSelectedFiles();
});
document.querySelector("#clear-files").addEventListener("click", () => {
  state.selectedFiles = [];
  renderSelectedFiles();
});
document.querySelector("#refresh-history").addEventListener("click", loadHistory);
document.querySelector("#history-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-history-job]");
  if (!button) return;
  const run = state.history.find((item) => item.job_id === button.dataset.historyJob);
  if (!run) return;
  showView("processing");
  pollDocuments([run]).catch((error) => {
    showView("upload");
    errorMessage.textContent = error.message;
    loadHistory();
  });
});

const stageLabels = {
  queued: "Waiting for an available worker...",
  starting: "Opening the document...",
  extracting: "Extracting native text and layout...",
  ocr: "Recognizing text on scanned pages...",
  finalizing: "Structuring the document result...",
  analyzing: "Analyzing extracted content with local AI...",
  storing: "Storing customer files in Azure...",
  completed: "Complete",
};

function updateBatchProgress() {
  const jobs = state.jobs;
  const progress = jobs.length
    ? Math.round(jobs.reduce((total, job) => total + (job.progress || 0), 0) / jobs.length)
    : 0;
  const completed = jobs.filter((job) => job.status === "completed").length;
  const active = jobs.find((job) => job.status !== "completed") || jobs.at(-1);
  const stage = stageLabels[active?.stage] || "Processing document...";
  document.querySelector("#processing-title").textContent = jobs.length === 1
    ? "Reading every page"
    : `Processing ${jobs.length} documents`;
  document.querySelector("#processing-stage").textContent = jobs.length > 1
    ? `${completed} of ${jobs.length} complete · ${stage}`
    : stage;
  document.querySelector("#progress-bar").style.width = `${progress}%`;
  document.querySelector("#progress-value").textContent = `${progress}%`;
  document.querySelector(".progress-track").setAttribute("aria-valuenow", progress);
  document.querySelector("#batch-progress").innerHTML = jobs.length > 1
    ? jobs.map((job) => `<div class="batch-progress-item"><span>${escapeHtml(job.filename)}</span><span>${escapeHtml(job.stage || job.status)}</span></div>`).join("")
    : "";
}

function setJobsUrl(jobs) {
  const params = new URLSearchParams();
  for (const job of jobs) {
    params.append("job", job.job_id);
    params.append("document", job.document_id);
  }
  history.replaceState(null, "", `/?${params.toString()}`);
}

async function pollJob(job) {
  while (true) {
    const response = await fetch(`/api/v1/jobs/${job.job_id}`);
    if (!response.ok) throw new Error(`Could not read the status for ${job.filename}.`);
    const status = await response.json();
    Object.assign(job, status);
    updateBatchProgress();
    if (status.status === "completed") {
      const resultResponse = await fetch(`/api/v1/documents/${job.document_id}/result`);
      if (!resultResponse.ok) throw new Error(`The result for ${job.filename} could not be loaded.`);
      return resultResponse.json();
    }
    if (["failed", "cancelled"].includes(status.status)) {
      throw new Error(status.error || `Processing stopped for ${job.filename}.`);
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

async function pollDocuments(documents) {
  state.jobs = documents.map((document, index) => ({
    ...document,
    filename: document.filename || `Document ${index + 1}`,
    status: "queued",
    stage: "queued",
    progress: 0,
  }));
  setJobsUrl(state.jobs);
  storeJobLabels(state.jobs);
  storeActiveJobs(state.jobs);
  updateBatchProgress();
  state.results = await Promise.all(state.jobs.map(pollJob));
  state.result = state.results[0];
  state.page = 1;
  state.tab = "content";
  state.query = "";
  renderResult();
  showView("result");
  announce(`${state.results.length} document${state.results.length === 1 ? "" : "s"} processed.`);
  loadCostOverview();
  loadStorageOverview();
}

document.querySelector("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.selectedFiles.length) return;
  submitButton.disabled = true;
  errorMessage.textContent = "";
  showView("processing");
  state.jobs = state.selectedFiles.map((file) => ({ filename: file.name, status: "queued", stage: "queued", progress: 0 }));
  updateBatchProgress();
  announce("Document upload started.");
  try {
    const body = new FormData();
    state.selectedFiles.forEach((file) => body.append("files", file));
    state.selectedModels.forEach((model) => body.append("models", model));
    body.append("customer_id", state.selectedCustomer);
    const response = await fetch("/api/v1/documents/batch", { method: "POST", body });
    if (!response.ok) {
      const problem = await response.json();
      throw new Error(problem.detail || "The documents could not be uploaded.");
    }
    const upload = await response.json();
    announce("Upload complete. Processing started.");
    await pollDocuments(upload.documents);
  } catch (error) {
    showView("upload");
    errorMessage.textContent = error.message;
    submitButton.disabled = false;
    announce(error.message);
  }
});

function highlighted(value) {
  const text = escapeHtml(value);
  if (!state.query) return text;
  const escapedQuery = state.query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return text.replace(new RegExp(`(${escapedQuery})`, "gi"), "<mark>$1</mark>");
}

function flattenMetadata() {
  const result = state.result;
  const classification = result.document.classification;
  const analyses = getAnalyses(result);
  return {
    Filename: result.document.filename,
    "Document ID": result.document.id,
    Customer: result.document.customer?.name || "Not recorded",
    Category: formatCategory(classification?.category),
    "Classification method": formatCategory(classification?.method || "not available"),
    "Matched terms": classification?.matched_terms?.join(", ") || "None",
    "SHA-256": result.document.sha256,
    Size: formatBytes(result.document.size_bytes),
    Pages: result.document.page_count,
    Title: result.document.metadata.title || "Not provided",
    Author: result.document.metadata.author || "Not provided",
    "Schema version": result.schema_version,
    Duration: `${result.processing.duration_ms} ms`,
    "OCR languages": result.processing.ocr_languages.join(", "),
    "AI models": analyses.map((analysis) => analysis.model).filter(Boolean).join(", ") || "Not available",
    "AI evidence confidence": analyses.map((analysis) => {
      const score = Number(analysis.confidence?.score);
      return Number.isFinite(score)
        ? `${analysis.model}: ${Math.max(0, Math.min(100, Math.round(score)))}%`
        : `${analysis.model || "Model"}: not recorded`;
    }).join(" | "),
    "Azure container": result.storage?.container || "Not configured",
    "Storage status": formatCategory(result.storage?.status || "not recorded"),
    "Retention days": result.storage?.retention_days || "Not recorded",
    "Estimated total cost": result.cost_estimate
      ? formatCurrency(result.cost_estimate.estimated_total_usd)
      : "Not recorded",
  };
}

function renderCostAndStorage(canvas, result) {
  const cost = result.cost_estimate;
  const storage = result.storage || {};
  const total = cost ? formatCurrency(cost.estimated_total_usd) : "Not recorded";
  canvas.innerHTML = `
    <section class="cost-summary">
      <span class="analysis-provenance">Per-document estimate</span>
      <h2>${escapeHtml(total)}</h2>
      <p>${escapeHtml(cost?.disclaimer || "This run predates cost estimation.")}</p>
    </section>
    <dl class="cost-breakdown">
      <div><dt>Compute</dt><dd>${cost ? formatCurrency(cost.compute_usd) : "-"}</dd><small>${Number(cost?.runtime_ms || 0).toLocaleString()} ms runtime</small></div>
      <div><dt>Storage</dt><dd>${cost ? formatCurrency(cost.storage_for_retention_usd) : "-"}</dd><small>${formatBytes(cost?.stored_bytes)} for ${escapeHtml(cost?.retention_days || "-")} days</small></div>
      <div><dt>Transactions</dt><dd>${cost ? formatCurrency(cost.transactions_usd) : "-"}</dd><small>Writes and lifecycle deletions</small></div>
    </dl>
    <dl class="metadata-grid storage-metadata">
      <dt>Customer</dt><dd>${escapeHtml(result.document.customer?.name || "Not recorded")}</dd>
      <dt>Storage account</dt><dd>${escapeHtml(storage.account || "Not configured")}</dd>
      <dt>Container</dt><dd>${escapeHtml(storage.container || "Not configured")}</dd>
      <dt>Retention policy</dt><dd>${escapeHtml(storage.retention_policy || "Not recorded")}</dd>
      <dt>Source blob</dt><dd>${escapeHtml(storage.source_blob || "Not stored")}</dd>
      <dt>Result blob</dt><dd>${escapeHtml(storage.result_blob || "Not stored")}</dd>
      <dt>Storage status</dt><dd>${escapeHtml(storage.status || "Not recorded")}</dd>
    </dl>
  `;
}

function renderList(items, emptyMessage) {
  return items?.length
    ? `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
    : `<p class="empty-state">${escapeHtml(emptyMessage)}</p>`;
}

function getAnalyses(result) {
  return Array.isArray(result.analyses) && result.analyses.length
    ? result.analyses
    : [result.analysis || { status: "not_requested" }];
}

function normalizedConfidence(analysis) {
  const rawScore = Number(analysis.confidence?.score);
  return Number.isFinite(rawScore)
    ? Math.max(0, Math.min(100, Math.round(rawScore)))
    : null;
}

function renderConfidence(analysis) {
  const confidenceScore = normalizedConfidence(analysis);
  if (confidenceScore === null) {
    return '<div class="analysis-confidence unavailable"><span>Evidence confidence</span><strong>Not recorded</strong><small>This run predates confidence scoring.</small></div>';
  }
  return `<div class="analysis-confidence">
    <span>Evidence confidence</span>
    <strong>${confidenceScore}%</strong>
    <small>${escapeHtml(analysis.confidence.level || "unrated")} · extraction ${escapeHtml(analysis.confidence.extraction_quality)}% · context ${escapeHtml(analysis.confidence.context_coverage)}%</small>
  </div>`;
}

function formatModelDuration(value) {
  const duration = Number(value);
  if (!Number.isFinite(duration) || duration <= 0) return "Not reported";
  return duration >= 1000 ? `${(duration / 1000).toFixed(1)} s` : `${Math.round(duration)} ms`;
}

function renderEntities(analysis) {
  return analysis.entities?.length
    ? analysis.entities.map((entity) => `<span class="entity">${escapeHtml(entity.name)} <small>${escapeHtml(entity.type)}</small></span>`).join("")
    : '<p class="empty-state">No named entities detected.</p>';
}

function renderAnalysisBody(analysis) {
  if (analysis.status !== "completed") {
    return `<div class="model-analysis-error">Analysis ${escapeHtml(analysis.status.replaceAll("_", " "))}. ${escapeHtml(analysis.reason || "No result was returned.")}</div>`;
  }
  return `
    <section class="model-summary"><h4>Summary</h4><p>${escapeHtml(analysis.summary || "No summary generated.")}</p></section>
    <div class="model-output-sections">
      <section><h4>Key points</h4>${renderList(analysis.key_points, "No key points detected.")}</section>
      <section><h4>Entities</h4><div class="entity-list">${renderEntities(analysis)}</div></section>
      <section><h4>Action items</h4>${renderList(analysis.action_items, "No explicit action items detected.")}</section>
    </div>`;
}

function renderSingleAnalysis(canvas, analysis) {
  if (analysis.status !== "completed") {
    canvas.innerHTML = `<div class="empty-state">AI analysis is ${escapeHtml(analysis.status.replaceAll("_", " "))}. ${escapeHtml(analysis.reason || "Process this document with local AI enabled to generate insights.")}</div>`;
    return;
  }
  const confidenceScore = normalizedConfidence(analysis);
  canvas.innerHTML = `
    <section class="analysis-header">
      <div class="analysis-heading-row">
        <span class="analysis-provenance">Local AI · ${escapeHtml(analysis.model)}</span>
        ${renderConfidence(analysis)}
      </div>
      <p>${escapeHtml(analysis.summary || "No summary generated.")}</p>
      ${confidenceScore !== null ? '<small class="confidence-note">Measures extraction quality and context coverage, not the probability that generated claims are true.</small>' : ""}
    </section>
    <div class="analysis-grid">
      <section class="analysis-section"><h3>Key points</h3>${renderList(analysis.key_points, "No key points detected.")}</section>
      <section class="analysis-section"><h3>Entities</h3><div class="entity-list">${renderEntities(analysis)}</div></section>
      <section class="analysis-section"><h3>Action items</h3>${renderList(analysis.action_items, "No explicit action items detected.")}</section>
    </div>
  `;
}

function renderComparison(canvas, analyses) {
  const metrics = analyses.map((analysis) => `
    <tr>
      <th scope="row">${escapeHtml(analysis.model || "Unknown model")}</th>
      <td>${escapeHtml(analysis.status)}</td>
      <td>${escapeHtml(formatModelDuration(analysis.performance?.duration_ms))}</td>
      <td>${escapeHtml(analysis.performance?.output_tokens || "Not reported")}</td>
      <td>${normalizedConfidence(analysis) === null ? "Not recorded" : `${normalizedConfidence(analysis)}%`}</td>
    </tr>
  `).join("");
  canvas.innerHTML = `
    <section class="comparison-header">
      <span class="analysis-provenance">Local model comparison</span>
      <h2>${analyses.length} models analyzed the same extracted evidence</h2>
      <p>Compare runtime and output shape first, then review each generated claim against the extracted document.</p>
    </section>
    <div class="comparison-scoreboard-wrap">
      <table class="comparison-scoreboard">
        <thead><tr><th scope="col">Model</th><th scope="col">Status</th><th scope="col">Runtime</th><th scope="col">Output tokens</th><th scope="col">Evidence confidence</th></tr></thead>
        <tbody>${metrics}</tbody>
      </table>
    </div>
    <div class="model-comparison">
      ${analyses.map((analysis, index) => `
        <article class="model-analysis">
          <header class="model-analysis-header">
            <div><span>Model ${String(index + 1).padStart(2, "0")}</span><h3>${escapeHtml(analysis.model || "Unknown model")}</h3></div>
            ${renderConfidence(analysis)}
          </header>
          ${renderAnalysisBody(analysis)}
        </article>
      `).join("")}
    </div>
    <small class="confidence-note">Evidence confidence is input quality, not a probability that generated claims are true.</small>
  `;
}

function renderAnalysis(canvas, result) {
  const analyses = getAnalyses(result);
  if (analyses.length > 1) {
    renderComparison(canvas, analyses);
  } else {
    renderSingleAnalysis(canvas, analyses[0]);
  }
}

function renderPage() {
  const canvas = document.querySelector("#result-content");
  const result = state.result;
  document.querySelector(".search-box").hidden = ["analysis", "cost", "metadata", "warnings"].includes(state.tab);
  if (state.tab === "analysis") {
    renderAnalysis(canvas, result);
    return;
  }
  if (state.tab === "cost") {
    renderCostAndStorage(canvas, result);
    return;
  }
  if (state.tab === "metadata") {
    canvas.innerHTML = `<dl class="metadata-grid">${Object.entries(flattenMetadata()).map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl>`;
    return;
  }
  if (state.tab === "warnings") {
    const warnings = result.processing.warnings;
    canvas.innerHTML = warnings.length
      ? warnings.map((warning) => `<div class="content-block"><strong>${escapeHtml(warning.code)}</strong><p>${escapeHtml(warning.message)}</p></div>`).join("")
      : '<div class="empty-state">No processing warnings. Every page completed successfully.</div>';
    return;
  }
  const page = result.pages.find((item) => item.page_number === state.page) || result.pages[0];
  const header = `<header class="page-heading"><h2>Page ${page.page_number}</h2><span class="source-badge">${escapeHtml(page.text_source)} text</span></header>`;
  if (state.tab === "text") {
    canvas.innerHTML = `${header}<div class="plain-text">${highlighted(page.text)}</div>`;
    return;
  }
  const blocks = page.blocks.filter((block) => !state.query || block.text.toLowerCase().includes(state.query.toLowerCase()));
  canvas.innerHTML = `${header}${blocks.length ? blocks.map((block) => `<section class="content-block ${escapeHtml(block.type)}">${highlighted(block.text)}</section>`).join("") : '<div class="empty-state">No matching content on this page.</div>'}`;
}

function selectResult(index) {
  state.result = state.results[index];
  state.page = 1;
  state.query = "";
  document.querySelector("#search-input").value = "";
  renderResult();
}

function renderResult() {
  const result = state.result;
  const resultIndex = state.results.indexOf(result);
  const batchPrefix = state.results.length > 1 ? `${resultIndex + 1} of ${state.results.length} · ` : "";
  document.querySelector("#classification-category").textContent = formatCategory(result.document.classification?.category);
  document.querySelector("#result-title").textContent = result.document.filename;
  const customerName = result.document.customer?.name || "Customer not recorded";
  const estimatedCost = result.cost_estimate
    ? formatCurrency(result.cost_estimate.estimated_total_usd)
    : "Cost not recorded";
  document.querySelector("#result-summary").textContent = `${batchPrefix}${customerName} · ${result.document.page_count} page${result.document.page_count === 1 ? "" : "s"} · ${formatBytes(result.document.size_bytes)} · ${estimatedCost}`;
  document.querySelector("#download-result").href = `/api/v1/documents/${result.document.id}/download`;
  const documentRail = document.querySelector("#document-rail");
  documentRail.hidden = state.results.length < 2;
  document.querySelector("#document-list").innerHTML = state.results.map((item, index) => `<button class="document-button ${item === result ? "active" : ""}" type="button" data-document-index="${index}" title="${escapeHtml(item.document.filename)}">${escapeHtml(item.document.filename)}</button>`).join("");
  document.querySelectorAll(".document-button").forEach((button) => button.addEventListener("click", () => selectResult(Number(button.dataset.documentIndex))));
  document.querySelector("#page-list").innerHTML = result.pages.map((page) => `<button class="page-button ${page.page_number === state.page ? "active" : ""}" type="button" data-page="${page.page_number}">Page ${page.page_number}</button>`).join("");
  document.querySelectorAll(".page-button").forEach((button) => button.addEventListener("click", () => {
    state.page = Number(button.dataset.page);
    renderResult();
  }));
  renderPage();
}

document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
  state.tab = tab.dataset.tab;
  document.querySelectorAll(".tab").forEach((item) => {
    const selected = item === tab;
    item.classList.toggle("active", selected);
    item.setAttribute("aria-selected", selected);
  });
  renderPage();
}));
document.querySelector("#search-input").addEventListener("input", (event) => {
  state.query = event.target.value.trim();
  renderPage();
});
document.querySelector("#new-document").addEventListener("click", () => {
  sessionStorage.removeItem(activeJobsStorageKey);
  sessionStorage.removeItem(jobLabelsStorageKey);
  history.replaceState(null, "", "/");
  window.location.reload();
});

const params = new URLSearchParams(window.location.search);
const jobIds = params.getAll("job");
const documentIds = params.getAll("document");
const storedJobs = readActiveJobs();
const jobLabels = {
  ...Object.fromEntries(storedJobs.map((job) => [job.job_id, job.filename])),
  ...readJobLabels(),
};
const urlJobs = jobIds.length && jobIds.length === documentIds.length
  ? jobIds.map((jobId, index) => ({
      job_id: jobId,
      document_id: documentIds[index],
      filename: jobLabels[jobId] || `Document ${index + 1}`,
    }))
  : [];
const jobsToResume = urlJobs.length ? urlJobs : storedJobs;
async function initialize() {
  try {
    await Promise.all([loadCustomers(), loadModels()]);
  } catch (error) {
    errorMessage.textContent = error.message;
  }
  loadCostOverview();
  loadStorageOverview();
  if (jobsToResume.length) {
    showView("processing");
    pollDocuments(jobsToResume).catch((error) => {
      showView("upload");
      errorMessage.textContent = error.message;
      loadHistory();
    });
  } else {
    loadHistory();
  }
}

initialize();