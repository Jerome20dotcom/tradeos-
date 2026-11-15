const state = {
  token: sessionStorage.getItem("tradeos_token"),
  userId: sessionStorage.getItem("tradeos_user_id"),
  email: sessionStorage.getItem("tradeos_email"),
  workspaces: [],
  workspace: null,
  products: [],
  customers: [],
  sales: [],
  copilotAvailable: false,
  pane: "dashboard",
  toastTimer: null,
};

const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
  if (options.body) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) signOut(false);
    throw new Error(data.detail || `Request failed (${response.status})`);
  }
  return data;
}

async function requestVerification() {
  const email = byId("loginEmail").value.trim();
  if (!email) {
    byId("loginEmail").focus();
    showToast("Enter your email address first.", true);
    return;
  }
  try {
    const result = await api("/v1/auth/verification/request", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
    showToast(result.message);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function requestPasswordReset(event) {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const button = event.currentTarget.querySelector('[type="submit"]');
  setLoading(button, true, "Sending...");
  try {
    const result = await api("/v1/auth/password-reset/request", {
      method: "POST",
      body: JSON.stringify({ email: data.get("email").trim() }),
    });
    byId("resetRequestDialog").close();
    event.currentTarget.reset();
    showToast(result.message);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setLoading(button, false);
  }
}

async function confirmPasswordReset(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const password = data.get("password");
  if (password !== data.get("confirm_password")) {
    showToast("The passwords do not match.", true);
    return;
  }
  const button = form.querySelector('[type="submit"]');
  setLoading(button, true, "Updating...");
  try {
    const result = await api("/v1/auth/password-reset/confirm", {
      method: "POST",
      body: JSON.stringify({ token: data.get("token"), password }),
    });
    byId("resetConfirmDialog").close();
    form.reset();
    showToast(result.message);
    selectAuthTab("login");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setLoading(button, false);
  }
}

function showToast(message, isError = false) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("visible");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => toast.classList.remove("visible"), 3600);
}

function setLoading(button, loading, label) {
  if (!button) return;
  button.disabled = loading;
  if (loading) {
    button.dataset.originalLabel = button.innerHTML;
    button.textContent = label;
  } else if (button.dataset.originalLabel) {
    button.innerHTML = button.dataset.originalLabel;
    delete button.dataset.originalLabel;
  }
}

function showSignedOut() {
  byId("loginView").hidden = false;
  byId("appView").hidden = true;
}

function signOut(showMessage = true) {
  state.token = null;
  state.userId = null;
  state.email = null;
  state.workspaces = [];
  state.workspace = null;
  state.products = [];
  state.customers = [];
  state.sales = [];
  state.copilotAvailable = false;
  sessionStorage.removeItem("tradeos_token");
  sessionStorage.removeItem("tradeos_user_id");
  sessionStorage.removeItem("tradeos_email");
  sessionStorage.removeItem("tradeos_workspace_id");
  showSignedOut();
  if (showMessage) showToast("You have signed out.");
}

async function startDevelopmentSession(button) {
  setLoading(button, true, "Opening your workspace...");
  try {
    const session = await api("/v1/dev/session", { method: "POST" });
    await startAuthenticatedSession({ ...session, email: "Development account" });
  } catch (error) {
    showToast(`${error.message}. Development sign-in is only available in development mode.`, true);
  } finally {
    setLoading(button, false);
  }
}

async function startAuthenticatedSession(session) {
  state.token = session.access_token;
  state.userId = session.user_id;
  state.email = session.email;
  sessionStorage.setItem("tradeos_token", state.token);
  sessionStorage.setItem("tradeos_user_id", state.userId);
  if (state.email) sessionStorage.setItem("tradeos_email", state.email);
  await loadApplication();
}

async function loadApplication() {
  byId("loginView").hidden = true;
  byId("appView").hidden = false;
  byId("userShortId").textContent = state.userId ? state.userId.slice(0, 8) : "";
  byId("userAvatar").textContent = (state.email || state.userId || "T").slice(0, 1).toUpperCase();
  document.querySelector(".account-copy strong").textContent = state.email || "Development account";
  await loadWorkspaces();
  await selectPane(state.pane, false);
}

function selectAuthTab(name) {
  document.querySelectorAll("[data-auth-tab]").forEach((tab) => {
    const active = tab.dataset.authTab === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  byId("loginForm").hidden = name !== "login";
  byId("registerForm").hidden = name !== "register";
  (name === "login" ? byId("loginEmail") : byId("registerEmail")).focus();
}

async function submitCredentials(event, endpoint) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('[type="submit"]');
  const data = new FormData(form);
  setLoading(button, true, endpoint === "register" ? "Creating account..." : "Signing in...");
  try {
    const result = await api(`/v1/auth/${endpoint}`, {
      method: "POST",
      body: JSON.stringify({
        email: data.get("email").trim(),
        password: data.get("password"),
      }),
    });
    form.reset();
    if (endpoint === "register") {
      selectAuthTab("login");
      showToast(result.message);
    } else {
      await startAuthenticatedSession(result);
      showToast("Signed in.");
    }
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setLoading(button, false);
  }
}

async function loadWorkspaces() {
  state.workspaces = await api("/v1/me/workspaces");
  const requestedId = sessionStorage.getItem("tradeos_workspace_id");
  state.workspace = state.workspaces.find((item) => item.id === requestedId) || state.workspaces[0] || null;
  byId("workspaceSelect").innerHTML = state.workspaces.length
    ? state.workspaces.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join("")
    : `<option value="">No workspace selected</option>`;
  if (state.workspace) {
    sessionStorage.setItem("tradeos_workspace_id", state.workspace.id);
    byId("workspaceSelect").value = state.workspace.id;
    byId("workspaceRole").textContent = `${state.workspace.role} · ${state.workspace.base_currency}`;
  } else {
    sessionStorage.removeItem("tradeos_workspace_id");
    byId("workspaceRole").textContent = "No workspace selected";
  }
  document.querySelector('[data-view="activity"]').hidden =
    !state.workspace || !["owner", "admin"].includes(state.workspace.role);
  await loadWorkspaceData();
}

async function loadWorkspaceData() {
  if (!state.workspace) {
    state.products = [];
    state.customers = [];
    state.sales = [];
    state.copilotAvailable = false;
  } else {
    const root = `/v1/w/${state.workspace.id}`;
    [state.products, state.customers, state.sales] = await Promise.all([
      api(`${root}/products`),
      api(`${root}/customers`),
      api(`${root}/sales`),
    ]);
    const config = await api(`${root}/copilot/config`);
    state.copilotAvailable = config.available;
    byId("copilotStatus").textContent = config.available
      ? `Connected · ${config.provider} · approval required`
      : "AI provider is not configured";
    byId("copilotUnavailable").hidden = config.available;
    byId("copilotInput").disabled = !config.available;
    byId("copilotSend").disabled = !config.available;
  }
  if (!state.workspace) {
    byId("copilotStatus").textContent = "Choose a workspace to begin";
    byId("copilotUnavailable").hidden = false;
    byId("copilotInput").disabled = true;
    byId("copilotSend").disabled = true;
  }
  renderProducts();
  renderCustomers();
  renderSales();
  renderDashboard();
}

async function loadProducts() {
  state.products = state.workspace
    ? await api(`/v1/w/${state.workspace.id}/products`)
    : [];
  renderProducts();
  renderDashboard();
}

function formatMoney(minor, currency = state.workspace?.base_currency || "JMD") {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(Number(minor) / 100);
  } catch {
    return `${currency} ${(Number(minor) / 100).toFixed(2)}`;
  }
}

function productAvatar(product, index) {
  const initial = escapeHtml((product.name || "?").trim().slice(0, 1).toUpperCase());
  return `<span class="product-avatar tone-${index % 4}">${initial}</span>`;
}

function renderDashboard() {
  const hasWorkspace = Boolean(state.workspace);
  byId("emptyWorkspace").hidden = hasWorkspace;
  byId("dashboardContent").hidden = !hasWorkspace;
  if (!hasWorkspace) return;

  const stock = state.products.reduce((sum, item) => sum + Number(item.stock_quantity), 0);
  const sales = state.sales.reduce((sum, item) => sum + Number(item.total_minor), 0);
  byId("metricProducts").textContent = String(state.products.length);
  byId("metricStock").textContent = String(stock);
  byId("metricSales").textContent = formatMoney(sales);

  const recent = state.products.slice(0, 4);
  byId("recentProducts").innerHTML = recent.length
    ? recent.map((product, index) => `
      <div class="recent-row">
        ${productAvatar(product, index)}
        <span class="recent-name"><strong>${escapeHtml(product.name)}</strong><small>${escapeHtml(product.stock_quantity)} ${escapeHtml(product.unit)} in stock</small></span>
        <span class="recent-price">${formatMoney(product.price_minor)}</span>
      </div>`).join("")
    : `<div class="table-empty"><span>▦</span><strong>No products yet</strong><p>Add your first product to see it here.</p></div>`;
}

function renderProducts() {
  const query = byId("productSearch").value.trim().toLowerCase();
  const filtered = state.products.filter((item) => item.name.toLowerCase().includes(query));
  const hasWorkspace = Boolean(state.workspace);
  const hasProducts = state.products.length > 0;
  byId("productNavCount").textContent = hasProducts ? String(state.products.length) : "";
  byId("inventoryCount").textContent = String(state.products.length);
  byId("tableCurrency").textContent = state.workspace?.base_currency || "—";
  byId("noWorkspaceProducts").hidden = !hasWorkspace || hasProducts || Boolean(query);
  byId("noSearchResults").hidden = !hasProducts || filtered.length > 0;
  byId("productRows").innerHTML = filtered.map((product, index) => {
    const margin = Number(product.price_minor) > 0
      ? Math.round((Number(product.price_minor) - Number(product.cost_minor)) / Number(product.price_minor) * 100)
      : 0;
    return `<tr>
      <td><span class="table-product">${productAvatar(product, index)}<strong>${escapeHtml(product.name)}</strong></span></td>
      <td>${escapeHtml(product.unit)}</td>
      <td class="${Number(product.stock_quantity) < 5 ? "stock-low" : ""}">${escapeHtml(product.stock_quantity)}</td>
      <td>${formatMoney(product.price_minor)}</td>
      <td>${formatMoney(product.cost_minor)}</td>
      <td><span class="margin-value">${margin}%</span></td>
      <td><span class="row-actions">
        <button class="row-action" data-action="edit-product" data-product-id="${escapeHtml(product.id)}" aria-label="Edit ${escapeHtml(product.name)}" title="Edit">✎</button>
        <button class="row-action delete" data-action="delete-product" data-product-id="${escapeHtml(product.id)}" aria-label="Delete ${escapeHtml(product.name)}" title="Delete">×</button>
      </span></td>
    </tr>`;
  }).join("");
  byId("tableSummary").textContent = `Showing ${filtered.length} of ${state.products.length} product${state.products.length === 1 ? "" : "s"}`;
}

function renderCustomers() {
  const query = byId("customerSearch").value.trim().toLowerCase();
  const filtered = state.customers.filter((customer) =>
    `${customer.name} ${customer.email} ${customer.phone}`.toLowerCase().includes(query));
  byId("customerNavCount").textContent = state.customers.length ? String(state.customers.length) : "";
  byId("customerCount").textContent = String(state.customers.length);
  byId("noCustomers").hidden = !state.workspace || state.customers.length > 0 || Boolean(query);
  byId("noCustomerResults").hidden = !state.customers.length || filtered.length > 0;
  byId("customerRows").innerHTML = filtered.map((customer, index) => `
    <tr>
      <td><span class="table-product">${productAvatar(customer, index)}<strong>${escapeHtml(customer.name)}</strong></span></td>
      <td>${escapeHtml(customer.email || "—")}</td>
      <td>${escapeHtml(customer.phone || "—")}</td>
      <td><span class="row-actions">
        <button class="row-action" data-action="edit-customer" data-customer-id="${escapeHtml(customer.id)}" aria-label="Edit ${escapeHtml(customer.name)}" title="Edit">✎</button>
        <button class="row-action delete" data-action="delete-customer" data-customer-id="${escapeHtml(customer.id)}" aria-label="Delete ${escapeHtml(customer.name)}" title="Delete">×</button>
      </span></td>
    </tr>`).join("");
  byId("customerSummary").textContent =
    `Showing ${filtered.length} of ${state.customers.length} customer${state.customers.length === 1 ? "" : "s"}`;
  byId("saleCustomer").innerHTML = `<option value="">Walk-in customer</option>` +
    state.customers.map((customer) =>
      `<option value="${escapeHtml(customer.id)}">${escapeHtml(customer.name)}</option>`).join("");
}

function renderSales() {
  byId("salesNavCount").textContent = state.sales.length ? String(state.sales.length) : "";
  byId("salesCount").textContent = String(state.sales.length);
  byId("noSales").hidden = !state.workspace || state.sales.length > 0;
  byId("salesRows").innerHTML = state.sales.map((sale) => {
    const date = new Date(sale.created_at).toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    });
    const itemSummary = sale.items.map((item) =>
      `${escapeHtml(item.quantity)} × ${escapeHtml(item.product_name)}`).join(", ");
    return `<tr>
      <td><strong>${escapeHtml(sale.id.slice(0, 8).toUpperCase())}</strong></td>
      <td>${escapeHtml(date)}</td>
      <td>${escapeHtml(sale.customer_name || "Walk-in")}</td>
      <td>${itemSummary}</td>
      <td><strong>${formatMoney(sale.total_minor)}</strong></td>
    </tr>`;
  }).join("");
  byId("salesSummary").textContent = `Showing ${state.sales.length} sale${state.sales.length === 1 ? "" : "s"}`;
}

function addCopilotMessage(role, text) {
  const message = document.createElement("div");
  message.className = `copilot-message ${role}`;
  if (role === "assistant") {
    const avatar = document.createElement("span");
    avatar.className = "message-avatar";
    avatar.textContent = "✳";
    message.append(avatar);
  }
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.textContent = text;
  message.append(bubble);
  byId("copilotMessages").append(message);
  message.scrollIntoView({ block: "nearest", behavior: "smooth" });
  return message;
}

function renderCopilotProposal(proposal, parent) {
  const card = document.createElement("article");
  card.className = "copilot-pending";
  card.dataset.proposalId = proposal.id;
  const label = document.createElement("span");
  label.textContent = "PROPOSED CHANGE";
  const title = document.createElement("h3");
  title.textContent = proposal.title;
  const description = document.createElement("p");
  description.textContent = proposal.description;
  const footer = document.createElement("footer");
  const expires = document.createElement("small");
  expires.textContent = "Expires in 5 minutes";
  const cancel = document.createElement("button");
  cancel.className = "button button-outline";
  cancel.type = "button";
  cancel.dataset.action = "copilot-cancel";
  cancel.textContent = "Cancel";
  const confirm = document.createElement("button");
  confirm.className = "button button-primary";
  confirm.type = "button";
  confirm.dataset.action = "copilot-confirm";
  confirm.textContent = "Confirm change";
  footer.append(expires, cancel, confirm);
  card.append(label, title, description, footer);
  parent.after(card);
}

async function submitCopilotMessage(event) {
  event.preventDefault();
  if (!state.workspace || !state.copilotAvailable) {
    showToast("Copilot is not configured for this workspace.", true);
    return;
  }
  const input = byId("copilotInput");
  const message = input.value.trim();
  if (!message) return;
  addCopilotMessage("user", message);
  input.value = "";
  const button = byId("copilotSend");
  setLoading(button, true, "Thinking...");
  input.disabled = true;
  try {
    const result = await api(`/v1/w/${state.workspace.id}/copilot/chat`, {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    const reply = addCopilotMessage("assistant", result.reply);
    if (result.proposal) renderCopilotProposal(result.proposal, reply);
  } catch (error) {
    addCopilotMessage("assistant", error.message);
  } finally {
    setLoading(button, false);
    input.disabled = !state.copilotAvailable;
    if (state.copilotAvailable) input.focus();
  }
}

async function confirmCopilotProposal(button) {
  const card = button.closest(".copilot-pending");
  if (!card || !state.workspace) return;
  const proposalId = card.dataset.proposalId;
  setLoading(button, true, "Applying...");
  card.querySelectorAll("button").forEach((item) => { item.disabled = true; });
  try {
    const result = await api(
      `/v1/w/${state.workspace.id}/copilot/proposals/${proposalId}/confirm`,
      { method: "POST" },
    );
    card.querySelector("footer").textContent = "Confirmed";
    card.classList.add("copilot-completed");
    addCopilotMessage("assistant", result.message);
    await loadWorkspaceData();
  } catch (error) {
    card.querySelector("footer").textContent = error.message;
    card.classList.add("copilot-failed");
  }
}

async function cancelCopilotProposal(button) {
  const card = button.closest(".copilot-pending");
  if (!card || !state.workspace) return;
  card.querySelectorAll("button").forEach((item) => { item.disabled = true; });
  try {
    const result = await api(
      `/v1/w/${state.workspace.id}/copilot/proposals/${card.dataset.proposalId}/cancel`,
      { method: "POST" },
    );
    card.querySelector("footer").textContent = result.message;
    card.classList.add("copilot-completed");
  } catch (error) {
    card.querySelector("footer").textContent = error.message;
    card.classList.add("copilot-failed");
  }
}

async function renderActivity() {
  const rows = state.workspace
    ? await api(`/v1/w/${state.workspace.id}/audit-log`)
    : [];
  byId("emptyActivity").hidden = rows.length > 0;
  byId("activityRows").innerHTML = rows.map((row) => {
    const action = row.action.charAt(0).toUpperCase() + row.action.slice(1);
    const entity = row.entity.charAt(0).toUpperCase() + row.entity.slice(1);
    const name = row.entity_id ? `Item ${row.entity_id.slice(0, 8)}` : "Workspace";
    const symbol = row.action === "delete" ? "×" : row.action === "create" ? "+" : "↗";
    const time = new Date(row.at).toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    });
    return `<div class="activity-item">
      <span class="activity-symbol ${row.action === "delete" ? "delete" : ""}">${symbol}</span>
      <span class="activity-copy"><strong>${escapeHtml(action)} ${escapeHtml(entity.toLowerCase())}</strong><small>${escapeHtml(name)} · by ${escapeHtml(row.actor_id?.slice(0, 8) || "system")}</small></span>
      <time class="activity-time">${escapeHtml(time)}</time>
    </div>`;
  }).join("");
}

async function selectPane(name, updateHistory = true) {
  const pane = document.querySelector(`[data-pane="${name}"]`);
  if (!pane) return;
  state.pane = name;
  document.querySelectorAll(".page-pane").forEach((item) => item.classList.toggle("active", item === pane));
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
  const title = name === "dashboard" ? "Overview" : name.charAt(0).toUpperCase() + name.slice(1);
  byId("breadcrumbTitle").textContent = title;
  if (updateHistory && name === "activity") {
    try {
      await renderActivity();
    } catch (error) {
      showToast(error.message, true);
    }
  }
  document.querySelector(".sidebar").classList.remove("menu-open");
}

function openWorkspaceDialog() {
  byId("workspaceForm").reset();
  byId("workspaceInputCurrency").value = state.workspace?.base_currency || "JMD";
  byId("workspaceDialog").showModal();
  byId("workspaceInputName").focus();
}

function openProductDialog(product = null) {
  if (!state.workspace) {
    showToast("Create a workspace before adding products.", true);
    return;
  }
  const form = byId("productForm");
  form.reset();
  form.dataset.productId = product?.id || "";
  byId("productDialogTitle").textContent = product ? "Edit product" : "Add a product";
  byId("productSubmit").innerHTML = product ? "Save changes <span>→</span>" : "Save product <span>→</span>";
  byId("productName").value = product?.name || "";
  byId("productUnit").value = product?.unit || "pcs";
  byId("productPrice").value = product ? (Number(product.price_minor) / 100).toFixed(2) : "";
  byId("productCost").value = product ? (Number(product.cost_minor) / 100).toFixed(2) : "";
  byId("productStock").value = product?.stock_quantity ?? 0;
  const currency = state.workspace.base_currency;
  byId("priceCurrency").textContent = `(${currency})`;
  byId("costCurrency").textContent = `(${currency})`;
  byId("productDialog").showModal();
  byId("productName").focus();
}

async function submitWorkspace(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('[type="submit"]');
  const data = new FormData(form);
  setLoading(button, true, "Creating...");
  try {
    const workspace = await api("/v1/workspaces", {
      method: "POST",
      body: JSON.stringify({
        name: data.get("name").trim(),
        base_currency: data.get("base_currency").trim().toUpperCase(),
      }),
    });
    byId("workspaceDialog").close();
    sessionStorage.setItem("tradeos_workspace_id", workspace.id);
    await loadWorkspaces();
    showToast("Workspace created.");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setLoading(button, false);
  }
}

async function submitProduct(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = byId("productSubmit");
  const data = new FormData(form);
  const price = Number(data.get("price"));
  const cost = Number(data.get("cost"));
  if (!Number.isFinite(price) || !Number.isFinite(cost) || price * 100 > 1e12 || cost * 100 > 1e12) {
    showToast("Enter valid prices within the supported range.", true);
    return;
  }
  const product = {
    name: data.get("name").trim(),
    unit: data.get("unit").trim(),
    price_minor: Math.round(price * 100),
    cost_minor: Math.round(cost * 100),
    stock_quantity: Number(data.get("stock_quantity")),
  };
  const productId = form.dataset.productId;
  setLoading(button, true, "Saving...");
  try {
    await api(productId
      ? `/v1/w/${state.workspace.id}/products/${productId}`
      : `/v1/w/${state.workspace.id}/products`, {
      method: productId ? "PUT" : "POST",
      body: JSON.stringify(product),
    });
    byId("productDialog").close();
    await loadProducts();
    renderSaleLines();
    showToast(productId ? "Product updated." : "Product added.");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setLoading(button, false);
  }
}

function openCustomerDialog(customer = null) {
  if (!state.workspace) {
    showToast("Create a workspace before adding customers.", true);
    return;
  }
  const form = byId("customerForm");
  form.reset();
  form.dataset.customerId = customer?.id || "";
  byId("customerDialogTitle").textContent = customer ? "Edit customer" : "Add a customer";
  byId("customerSubmit").innerHTML = customer ? "Save changes <span>→</span>" : "Save customer <span>→</span>";
  byId("customerName").value = customer?.name || "";
  byId("customerEmail").value = customer?.email || "";
  byId("customerPhone").value = customer?.phone || "";
  byId("customerDialog").showModal();
  byId("customerName").focus();
}

async function submitCustomer(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = byId("customerSubmit");
  const data = new FormData(form);
  const customerId = form.dataset.customerId;
  setLoading(button, true, "Saving...");
  try {
    await api(customerId
      ? `/v1/w/${state.workspace.id}/customers/${customerId}`
      : `/v1/w/${state.workspace.id}/customers`, {
      method: customerId ? "PUT" : "POST",
      body: JSON.stringify({
        name: data.get("name").trim(),
        email: data.get("email").trim(),
        phone: data.get("phone").trim(),
      }),
    });
    byId("customerDialog").close();
    state.customers = await api(`/v1/w/${state.workspace.id}/customers`);
    renderCustomers();
    showToast(customerId ? "Customer updated." : "Customer added.");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setLoading(button, false);
  }
}

async function deleteCustomer(customerId) {
  const customer = state.customers.find((item) => item.id === customerId);
  if (!customer || !window.confirm(`Delete "${customer.name}" from this workspace?`)) return;
  try {
    await api(`/v1/w/${state.workspace.id}/customers/${customerId}`, { method: "DELETE" });
    state.customers = await api(`/v1/w/${state.workspace.id}/customers`);
    renderCustomers();
    showToast("Customer deleted.");
  } catch (error) {
    showToast(error.message, true);
  }
}

function renderSaleLines(lines = null) {
  const available = state.products.filter((product) => Number(product.stock_quantity) > 0);
  const container = byId("saleLines");
  if (!lines) {
    lines = [...container.querySelectorAll(".sale-line")].map((row) => ({
      product_id: row.querySelector("select").value,
      quantity: row.querySelector("input").value,
    }));
    if (!lines.length && available.length) {
      lines = [{ product_id: available[0].id, quantity: 1 }];
    }
  }
  const options = available.map((product) =>
    `<option value="${escapeHtml(product.id)}">${escapeHtml(product.name)} · ${escapeHtml(product.stock_quantity)} available · ${formatMoney(product.price_minor)}</option>`
  ).join("");
  container.innerHTML = available.length
    ? lines.map((line, index) => {
      const selected = available.some((product) => product.id === line.product_id)
        ? line.product_id
        : available[0].id;
      const product = available.find((item) => item.id === selected);
      return `<div class="sale-line">
        <label>Product<select name="product_id" required>${options}</select></label>
        <label>Quantity<input name="quantity" type="number" min="1" max="${product.stock_quantity}" value="${escapeHtml(line.quantity || 1)}" required></label>
        <button class="sale-line-remove" type="button" data-action="remove-sale-line" data-index="${index}" aria-label="Remove item" title="Remove item">×</button>
      </div>`;
    }).join("")
    : `<div class="table-empty"><strong>No products in stock</strong><p>Add stock to at least one product before recording a sale.</p></div>`;
  [...container.querySelectorAll(".sale-line")].forEach((row, index) => {
    row.querySelector("select").value = available.some((product) => product.id === lines[index].product_id)
      ? lines[index].product_id
      : available[0].id;
  });
  updateSaleTotal();
}

function updateSaleTotal() {
  const total = [...byId("saleLines").querySelectorAll(".sale-line")].reduce((sum, row) => {
    const product = state.products.find((item) => item.id === row.querySelector("select").value);
    return sum + (product ? Number(product.price_minor) * Number(row.querySelector("input").value || 0) : 0);
  }, 0);
  byId("saleTotal").textContent = formatMoney(total);
}

function openSaleDialog() {
  if (!state.workspace) {
    showToast("Create a workspace before recording sales.", true);
    return;
  }
  if (!state.products.some((product) => Number(product.stock_quantity) > 0)) {
    showToast("Add stock to a product before recording a sale.", true);
    return;
  }
  byId("saleCustomer").value = "";
  byId("saleLines").innerHTML = "";
  renderSaleLines([{ product_id: "", quantity: 1 }]);
  byId("saleDialog").showModal();
}

function addSaleLine() {
  const lines = [...byId("saleLines").querySelectorAll(".sale-line")].map((row) => ({
    product_id: row.querySelector("select").value,
    quantity: row.querySelector("input").value,
  }));
  const available = state.products.find((product) =>
    Number(product.stock_quantity) > 0 && !lines.some((line) => line.product_id === product.id));
  if (!available) {
    showToast("Every in-stock product is already in this sale.", true);
    return;
  }
  lines.push({ product_id: available.id, quantity: 1 });
  renderSaleLines(lines);
}

async function submitSale(event) {
  event.preventDefault();
  const items = [...byId("saleLines").querySelectorAll(".sale-line")].map((row) => ({
    product_id: row.querySelector("select").value,
    quantity: Number(row.querySelector("input").value),
  }));
  if (!items.length || items.some((item) => !item.product_id || !Number.isInteger(item.quantity) || item.quantity < 1)) {
    showToast("Add at least one product with a valid quantity.", true);
    return;
  }
  const customerId = byId("saleCustomer").value;
  const button = byId("saleSubmit");
  setLoading(button, true, "Saving sale...");
  try {
    await api(`/v1/w/${state.workspace.id}/sales`, {
      method: "POST",
      body: JSON.stringify({ customer_id: customerId || null, items }),
    });
    byId("saleDialog").close();
    await loadWorkspaceData();
    showToast("Sale recorded and stock updated.");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setLoading(button, false);
  }
}

async function deleteProduct(productId) {
  const product = state.products.find((item) => item.id === productId);
  if (!product || !window.confirm(`Delete "${product.name}" from this workspace?`)) return;
  try {
    await api(`/v1/w/${state.workspace.id}/products/${productId}`, { method: "DELETE" });
    await loadProducts();
    showToast("Product deleted.");
  } catch (error) {
    showToast(error.message, true);
  }
}

document.addEventListener("click", async (event) => {
  const viewButton = event.target.closest("[data-view]");
  if (viewButton) {
    selectPane(viewButton.dataset.view);
    return;
  }
  const button = event.target.closest("[data-action]");
  if (!button) return;
  switch (button.dataset.action) {
    case "dev-login":
      await startDevelopmentSession(button);
      break;
    case "auth-tab":
      selectAuthTab(button.dataset.authTab);
      break;
    case "copilot-confirm":
      await confirmCopilotProposal(button);
      break;
    case "copilot-cancel":
      await cancelCopilotProposal(button);
      break;
    case "forgot-password":
      byId("resetEmail").value = byId("loginEmail").value;
      byId("resetRequestDialog").showModal();
      byId("resetEmail").focus();
      break;
    case "resend-verification":
      await requestVerification();
      break;
    case "sign-out":
      signOut();
      break;
    case "create-workspace":
      openWorkspaceDialog();
      break;
    case "add-product":
      openProductDialog();
      break;
    case "add-customer":
      openCustomerDialog();
      break;
    case "edit-customer": {
      const customer = state.customers.find((item) => item.id === button.dataset.customerId);
      if (customer) openCustomerDialog(customer);
      break;
    }
    case "delete-customer":
      await deleteCustomer(button.dataset.customerId);
      break;
    case "record-sale":
      openSaleDialog();
      break;
    case "add-sale-line":
      addSaleLine();
      break;
    case "remove-sale-line": {
      const lines = [...byId("saleLines").querySelectorAll(".sale-line")].map((row) => ({
        product_id: row.querySelector("select").value,
        quantity: row.querySelector("input").value,
      }));
      lines.splice(Number(button.dataset.index), 1);
      renderSaleLines(lines);
      break;
    }
    case "edit-product": {
      const product = state.products.find((item) => item.id === button.dataset.productId);
      if (product) openProductDialog(product);
      break;
    }
    case "delete-product":
      await deleteProduct(button.dataset.productId);
      break;
    case "close-workspace":
      byId("workspaceDialog").close();
      break;
    case "close-product":
      byId("productDialog").close();
      break;
    case "close-customer":
      byId("customerDialog").close();
      break;
    case "close-sale":
      byId("saleDialog").close();
      break;
    case "close-reset-request":
      byId("resetRequestDialog").close();
      break;
    case "close-reset-confirm":
      byId("resetConfirmDialog").close();
      break;
    case "toggle-menu":
      document.querySelector(".sidebar").classList.toggle("menu-open");
      break;
  }
});

byId("workspaceInputCurrency").addEventListener("input", (event) => {
  event.target.value = event.target.value.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 3);
});
byId("workspaceSelect").addEventListener("change", async (event) => {
  const selected = state.workspaces.find((item) => item.id === event.target.value);
  if (!selected) return;
  state.workspace = selected;
  sessionStorage.setItem("tradeos_workspace_id", selected.id);
  byId("workspaceRole").textContent = `${selected.role} · ${selected.base_currency}`;
  document.querySelector('[data-view="activity"]').hidden = !["owner", "admin"].includes(selected.role);
  try {
    await loadWorkspaceData();
    if (state.pane === "activity") await renderActivity();
  } catch (error) {
    showToast(error.message, true);
  }
});
byId("workspaceForm").addEventListener("submit", submitWorkspace);
byId("productForm").addEventListener("submit", submitProduct);
byId("customerForm").addEventListener("submit", submitCustomer);
byId("saleForm").addEventListener("submit", submitSale);
byId("loginForm").addEventListener("submit", (event) => submitCredentials(event, "login"));
byId("registerForm").addEventListener("submit", (event) => submitCredentials(event, "register"));
byId("resetRequestForm").addEventListener("submit", requestPasswordReset);
byId("resetConfirmForm").addEventListener("submit", confirmPasswordReset);
byId("copilotForm").addEventListener("submit", submitCopilotMessage);
byId("copilotInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    byId("copilotForm").requestSubmit();
  }
});
byId("productSearch").addEventListener("input", renderProducts);
byId("customerSearch").addEventListener("input", renderCustomers);
byId("saleLines").addEventListener("input", updateSaleTotal);
byId("saleLines").addEventListener("change", (event) => {
  const row = event.target.closest(".sale-line");
  if (row && event.target.matches("select")) {
    const product = state.products.find((item) => item.id === event.target.value);
    if (product) row.querySelector("input").max = product.stock_quantity;
  }
  updateSaleTotal();
});

const date = new Date();
byId("todayLabel").textContent = date.toLocaleDateString(undefined, {
  weekday: "long", month: "long", day: "numeric",
}).toUpperCase();

async function initialize() {
  const config = await api("/v1/auth/config");
  byId("accountAuth").hidden = !config.email_password_available;
  document.querySelector(".dev-login-button").hidden = !config.development_login_available;
  byId("loginNote").textContent = config.development_login_available
    ? "Email sign-in or local development access"
    : "Secure account access";
  const url = new URL(window.location.href);
  const verificationToken = url.searchParams.get("verify");
  const resetToken = url.searchParams.get("reset");
  if (verificationToken || resetToken) {
    window.history.replaceState({}, "", url.pathname);
  }
  if (verificationToken) {
    const session = await api("/v1/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token: verificationToken }),
    });
    await startAuthenticatedSession(session);
    showToast("Email verified. Your account is ready.");
    return;
  }
  if (resetToken) {
    byId("resetToken").value = resetToken;
    byId("resetConfirmDialog").showModal();
  }
  if (state.token) {
    await loadApplication();
  } else {
    showSignedOut();
  }
}

document.querySelectorAll("[data-auth-tab]").forEach((tab) => {
  tab.addEventListener("click", () => selectAuthTab(tab.dataset.authTab));
});

initialize().catch((error) => {
  byId("accountAuth").hidden = true;
  document.querySelector(".dev-login-button").hidden = true;
  showSignedOut();
  showToast(`Could not load sign-in options: ${error.message}`, true);
});
