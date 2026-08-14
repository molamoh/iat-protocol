const API_BASE = "https://iat-protocol-latest.onrender.com";
const tracked = new Set();

// The site is split into focused pages. Keep one shared bundle, but make
// every feature optional so a page only needs to render the controls it uses.
function optionalElement(selector) {
  return document.querySelector(selector) || {
    value: "",
    hidden: true,
    disabled: false,
    className: "",
    textContent: "",
    addEventListener() {},
    replaceChildren() {},
    append() {},
    querySelector() { return optionalElement("__missing__"); },
    reportValidity() { return true; },
    reset() {},
  };
}

function trackFunnel(eventName) {
  if (tracked.has(eventName)) return;
  tracked.add(eventName);
  const safeName = String(eventName).replace(/[^a-z0-9-]/g, "");
  history.pushState({ iatFunnel: safeName }, "", `/funnel/${safeName}`);
}

function bindDraft(key, fields) {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(`iat_draft_${key}`) || "{}"); } catch (_) { saved = {}; }
  fields.forEach((field) => {
    if (!field) return;
    if (saved[field.id] !== undefined) field.value = saved[field.id];
    field.addEventListener("input", () => {
      try {
        const draft = JSON.parse(localStorage.getItem(`iat_draft_${key}`) || "{}");
        draft[field.id] = field.value;
        localStorage.setItem(`iat_draft_${key}`, JSON.stringify(draft));
      } catch (_) { /* storage is optional */ }
    });
  });
}

document.querySelectorAll("[data-funnel]").forEach((element) => {
  element.addEventListener("click", () => trackFunnel(element.dataset.funnel));
});

document.querySelectorAll("[data-copy]").forEach((button) => {
  button.addEventListener("click", async () => {
    await navigator.clipboard.writeText(button.dataset.copy);
    const original = button.textContent;
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = original; }, 1400);
  });
});

const form = optionalElement("#pilot-form");
const status = optionalElement("#form-status");

const sandboxService = optionalElement("#sandbox-service");
const sandboxGoal = optionalElement("#sandbox-goal");
const sandboxBudget = optionalElement("#sandbox-budget");
const sandboxStrategy = optionalElement("#sandbox-strategy");
const sandboxDiscover = optionalElement("#sandbox-discover");
const sandboxRun = optionalElement("#sandbox-run");
const sandboxStatus = optionalElement("#sandbox-status");
const sandboxResult = optionalElement("#sandbox-result");
bindDraft("buyer", [sandboxService, sandboxGoal, sandboxBudget, sandboxStrategy]);

function setSandboxStatus(message, type = "") {
  sandboxStatus.className = `sandbox-status${type ? ` ${type}` : ""}`;
  sandboxStatus.textContent = message;
}

function sandboxPayload() {
  return {
    service: sandboxService.value,
    goal: sandboxGoal.value.trim(),
    max_price: sandboxBudget.value.trim(),
    strategy: sandboxStrategy.value,
    required_capabilities: ["source_verification"],
  };
}

async function sandboxRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || "Sandbox request rejected");
  return result;
}

function showSandboxResult(result) {
  sandboxResult.hidden = false;
  sandboxResult.textContent = JSON.stringify(result, null, 2);
}

sandboxDiscover.addEventListener("click", async () => {
  sandboxDiscover.disabled = true;
  setSandboxStatus("Discovering a machine-readable offer…");
  try {
    const result = await sandboxRequest(`/sandbox/v1/offers?service=${encodeURIComponent(sandboxService.value)}`);
    showSandboxResult(result);
    setSandboxStatus(`${result.offers?.length || 0} eligible offer(s) discovered. You can now run the free simulation.`, "success");
    trackFunnel("sandbox-discovered");
  } catch (error) {
    setSandboxStatus(`Unable to discover: ${error.message}`, "error");
  } finally {
    sandboxDiscover.disabled = false;
  }
});

sandboxRun.addEventListener("click", async () => {
  const payload = sandboxPayload();
  if (!sandboxGoal.value.trim() || !/^\d{1,7}(\.\d{1,6})?$/.test(payload.max_price)) {
    setSandboxStatus("Enter a goal and a valid maximum budget, for example 2.00.", "error");
    return;
  }
  sandboxRun.disabled = true;
  setSandboxStatus("Running an isolated simulation…");
  try {
    const result = await sandboxRequest("/sandbox/v1/purchase", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": `site-demo-${crypto.randomUUID()}` },
      body: JSON.stringify(payload),
    });
    showSandboxResult(result);
    setSandboxStatus("Simulation complete. No funds moved and no supplier was contacted.", "success");
    trackFunnel("sandbox-completed");
  } catch (error) {
    setSandboxStatus(`Unable to simulate: ${error.message}`, "error");
  } finally {
    sandboxRun.disabled = false;
  }
});

const sellerEstimate = optionalElement("#seller-estimate");
const sellerStatus = optionalElement("#seller-status");
const sellerResult = optionalElement("#seller-result");
const sellerPrice = optionalElement("#seller-price");
const sellerOrders = optionalElement("#seller-orders");
const sellerRefunds = optionalElement("#seller-refunds");
const sellerCost = optionalElement("#seller-cost");

sellerEstimate.addEventListener("click", async () => {
  sellerEstimate.disabled = true;
  sellerStatus.className = "seller-status";
  sellerStatus.textContent = "Calculating with the active IAT policy…";
  try {
    const response = await sandboxRequest("/seller/v1/economics/estimate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        unit_price: sellerPrice.value.trim(),
        monthly_completed_orders: Number(sellerOrders.value),
        refund_rate: sellerRefunds.value.trim(),
        variable_cost_per_order: sellerCost.value.trim(),
      }),
    });
    const projection = response.monthly_projection;
    document.querySelector("#seller-commission").textContent = `${projection.protocol_commission} IAT`;
    document.querySelector("#seller-payout").textContent = `${projection.seller_payout} IAT`;
    document.querySelector("#seller-contribution").textContent = `${projection.seller_contribution_after_commission} IAT`;
    sellerResult.hidden = false;
    sellerStatus.className = "seller-status success";
    sellerStatus.textContent = `Active policy: ${response.policy.production_rate_percent}% commission.`;
    trackFunnel("seller-economics-estimated");
  } catch (error) {
    sellerStatus.className = "seller-status error";
    sellerStatus.textContent = `Unable to estimate: ${error.message}`;
  } finally {
    sellerEstimate.disabled = false;
  }
});

const sellerApiKey = optionalElement("#seller-api-key");
const sellerRegisterName = optionalElement("#seller-register-name");
const sellerRegisterWallet = optionalElement("#seller-register-wallet");
const sellerRegisterEmail = optionalElement("#seller-register-email");
const sellerRegisterWebsite = optionalElement("#seller-register-website");
const sellerRegisterSubmit = optionalElement("#seller-register-submit");
const sellerRegisterStatus = optionalElement("#seller-register-status");
const sellerRegisterKey = optionalElement("#seller-register-key");
const sellerRegisterKeyValue = optionalElement("#seller-register-key-value");
const sellerConsoleOpen = optionalElement("#seller-console-open");
const sellerConsoleStatus = optionalElement("#seller-console-status");
const sellerConsoleResult = optionalElement("#seller-console-result");
let sellerSessionHeaders = null;
bindDraft("seller-registration", [sellerRegisterName, sellerRegisterWallet, sellerRegisterEmail, sellerRegisterWebsite]);
bindDraft("seller-economics", [sellerPrice, sellerOrders, sellerRefunds, sellerCost]);

try {
  const savedSellerKey = sessionStorage.getItem("iat_seller_api_key");
  const savedSellerToken = sessionStorage.getItem("iat_seller_access_token");
  if (savedSellerKey) sellerSessionHeaders = { "X-Seller-API-Key": savedSellerKey };
  else if (savedSellerToken) sellerSessionHeaders = { Authorization: `Bearer ${savedSellerToken}` };
} catch (_) { /* private browsing may disable session storage */ }

function installSellerCapabilityForm() {
  const card = document.querySelector(".seller-console-card");
  if (!card || document.querySelector("#seller-agent-register")) return;
  const details = document.createElement("details");
  details.className = "seller-capability-form";
  details.open = true;
  details.innerHTML = `
    <summary>Register a service capability</summary>
    <p class="inbox-help">Add the agent endpoint that IAT may validate and expose to buyers.</p>
    <label>Agent identifier<input id="seller-agent-id" placeholder="research-agent-01"></label>
    <label>Service name<input id="seller-service" placeholder="Verified web research"></label>
    <label>Runtime adapter<select id="seller-runtime-adapter"><option value="http">HTTP</option><option value="openai_compatible">OpenAI-compatible</option><option value="mcp">MCP</option></select></label>
    <label>Runtime URL<input id="seller-runtime-url" type="url" placeholder="https://agent.example/run"></label>
    <label>Price in IAT<input id="seller-agent-price" value="1.00" inputmode="decimal"></label>
    <label>Capabilities (comma separated)<input id="seller-agent-capabilities" placeholder="web_research,source_verification"></label>
    <button id="seller-agent-register" class="button primary" type="button">Register capability</button>
    <p id="seller-agent-status" class="seller-status" role="status" aria-live="polite"></p>`;
  bindDraft("seller-capability", [details.querySelector("#seller-agent-id"), details.querySelector("#seller-service"), details.querySelector("#seller-runtime-adapter"), details.querySelector("#seller-runtime-url"), details.querySelector("#seller-agent-price"), details.querySelector("#seller-agent-capabilities")]);
  const resultPanel = card.querySelector("#seller-console-result");
  if (resultPanel) card.insertBefore(details, resultPanel); else card.append(details);
  const submit = details.querySelector("#seller-agent-register");
  submit.addEventListener("click", async () => {
    const headers = sellerSessionHeaders;
    const statusNode = details.querySelector("#seller-agent-status");
    if (!headers) {
      statusNode.className = "seller-status error";
      statusNode.textContent = "Open the private console first.";
      return;
    }
    const payload = {
      agent_id: details.querySelector("#seller-agent-id").value.trim(),
      service: details.querySelector("#seller-service").value.trim(),
      url: details.querySelector("#seller-runtime-url").value.trim(),
      runtime_adapter: details.querySelector("#seller-runtime-adapter").value,
      price: Number(details.querySelector("#seller-agent-price").value.trim()),
      capabilities: details.querySelector("#seller-agent-capabilities").value.split(",").map((item) => item.trim()).filter(Boolean),
    };
    if (payload.agent_id.length < 3 || payload.service.length < 3 || !/^https?:\/\//i.test(payload.url) || !Number.isFinite(payload.price) || payload.price < 0) {
      statusNode.className = "seller-status error";
      statusNode.textContent = "Enter an agent ID, service, valid HTTPS/HTTP URL and non-negative price.";
      return;
    }
    submit.disabled = true;
    statusNode.className = "seller-status";
    statusNode.textContent = "Validating runtime and registering capability…";
    try {
      const result = await sandboxRequest("/seller/register-agent", { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(payload) });
      if (result.status !== "ok") throw new Error(result.message || "Registration rejected");
      statusNode.className = "seller-status success";
      statusNode.textContent = `Capability registered: ${result.seller_agent_id || result.agent_id}. It remains subject to protocol verification.`;
      trackFunnel("seller-capability-registered");
    } catch (error) {
      statusNode.className = "seller-status error";
      statusNode.textContent = `Unable to register capability: ${error.message}`;
    } finally { submit.disabled = false; }
  });
}

function renderSellerGovernanceState(dashboard) {
  const card = document.querySelector(".seller-console-card");
  if (!card) return;
  let panel = document.querySelector("#seller-governance-state");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "seller-governance-state";
    panel.className = "seller-governance-state";
    const result = card.querySelector("#seller-console-result");
    if (result) card.append(panel); else card.append(panel);
  }
  const actions = Array.isArray(dashboard.next_required_actions) ? dashboard.next_required_actions : [];
  const runtime = dashboard.runtime || {};
  const seller = dashboard.seller || {};
  const recent = dashboard.recent || {};
  const agents = Array.isArray(recent.agents) ? recent.agents : [];
  const autonomous = Array.isArray(dashboard.autonomous_governance) ? dashboard.autonomous_governance : [];
  const onboarding = dashboard.onboarding_evidence || {};
  const onboardingReview = dashboard.onboarding_review || {};
  const capabilityReconciliation = dashboard.capability_reconciliation || {};
  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
  const checks = actions.length
    ? actions.map((item) => `<li><strong>${escapeHtml(item.type || "review")}</strong><span>${escapeHtml(item.action || item.reason || "pending")}</span></li>`).join("")
    : "<li><strong>Clear</strong><span>No additional governance action reported.</span></li>";
  const autonomousRows = autonomous.length
    ? autonomous.map((item) => {
      const factoryReview = item.factory_review || {};
      const factoryRequest = factoryReview.factory_request || factoryReview;
      const requestId = item.factory_request_id || factoryRequest.factory_request_id || "unknown";
      const currentCapabilityReview = String(requestId).startsWith("current_review_");
      const reviewLabel = currentCapabilityReview ? "Current capability review" : item.status === "completed" ? "Historical autonomous review" : "Autonomous review";
      if (item.status === "error") {
        return `<li><strong>Autonomous review · ${escapeHtml(requestId)}</strong><span>${escapeHtml(`${item.message || "runtime_error"}: ${item.error || item.error_type || "unknown"}`)}</span></li>`;
      }
      const reviewStatus = factoryRequest.governance_status || factoryReview.governance_status || item.review_evaluation?.readiness || item.status || "unknown";
      const storedReviews = Array.isArray(item.factory_reviews?.reviews) ? item.factory_reviews.reviews : [];
      const decision = item.governance_decision || {};
      const decisionReasons = Array.isArray(decision.risk_reasons) ? decision.risk_reasons.filter(Boolean) : [];
      const missingChecks = new Set();
      const storedReasons = new Set();
      storedReviews.forEach((review) => {
        if (review.review_reason) storedReasons.add(review.review_reason);
        let metadata = review.metadata || {};
        if (typeof metadata === "string") {
          try { metadata = JSON.parse(metadata); } catch (_) { metadata = {}; }
        }
        Object.entries(metadata.checks || {}).forEach(([name, passed]) => { if (!passed) missingChecks.add(name); });
      });
      const reviewReason = currentCapabilityReview && reviewStatus === "approved_current_capability"
        ? "current bounded capability quorum passed"
        : decisionReasons.length
        ? `risk ${decision.risk_score ?? "unknown"}: ${decisionReasons.join(", ")}`
        : missingChecks.size
          ? `required evidence missing: ${Array.from(missingChecks).join(", ")}`
          : storedReasons.size
            ? Array.from(storedReasons).join(", ")
            : factoryRequest.rejection_reason || factoryReview.rejection_reason || factoryReview.message || item.review_evaluation?.reason || "no_reason_reported";
      const snapshotNote = item.status === "completed" && !currentCapabilityReview ? "decision snapshot · " : "";
      return `<li><strong>${reviewLabel} · ${escapeHtml(requestId)}</strong><span>${escapeHtml(`${snapshotNote}${reviewStatus} · ${reviewReason}`)}</span></li>`;
    }).join("")
    : "<li><strong>Autonomous review</strong><span>No factory review recorded</span></li>";
  const emailVerified = Number(seller.email_verified || 0) === 1;
  const walletVerified = Number(seller.wallet_verified || 0) === 1;
  const runtimeVerified = Number(seller.runtime_verified || 0) === 1;
  const reachableRuntimes = agents.filter((agent) => ["validated", "healthy", "active"].includes(String(agent.runtime_validation_status || "").toLowerCase()));
  const emailAction = emailVerified ? "verified" : `<button type="button" class="button secondary seller-verify-email">Send verification email</button>`;
  const walletEvidence = walletVerified ? "verified by signature" : "sign in with the registered wallet to verify";
  const runtimeEvidence = reachableRuntimes.length ? `${reachableRuntimes.length} endpoint(s) reachable; domain control not yet verified` : "no reachable runtime registered";
  const hostedCandidate = reachableRuntimes.find((agent) => !String(agent.url || "").includes("iat-protocol-latest.onrender.com"))?.url || "";
  const runtimeControl = runtimeVerified ? "verified by domain challenge" : `<div class="seller-runtime-verification"><p class="seller-console-note">Use a runtime controlled by this seller. If you do not have one, deploy <a href="https://hub.docker.com/r/molamoh/iat-seller-runtime" target="_blank" rel="noopener noreferrer">molamoh/iat-seller-runtime:latest ↗</a>, then configure IAT_SELLER_ID, IAT_SELLER_VERIFICATION_TOKEN and a distinct IAT_RUNTIME_EXECUTION_SECRET.</p><input class="seller-runtime-url" type="url" value="${escapeHtml(reachableRuntimes[0]?.url || "")}" placeholder="https://your-seller-runtime.example"><button type="button" class="button secondary seller-runtime-challenge">Create challenge</button><button type="button" class="button secondary seller-runtime-confirm" hidden>Verify published file</button><pre class="seller-runtime-instructions" hidden></pre></div>`;
  const connectorControl = emailVerified && walletVerified ? `<div class="seller-connector-control"><p class="seller-console-note">IAT provides the isolated runtime for your registered capabilities. No URL, server or Docker process is required.</p><button type="button" class="button secondary seller-hosted-configure">Enable IAT-hosted runtime</button><button type="button" class="button secondary seller-connector-canary">Test runtime</button><pre class="seller-connector-key" hidden></pre><details><summary>External agent endpoint (advanced)</summary><input class="seller-hosted-agent-url" type="url" value="${escapeHtml(hostedCandidate)}" placeholder="https://your-agent.example/execute"><input class="seller-hosted-agent-secret" type="password" autocomplete="new-password" placeholder="Agent access token (optional)"><button type="button" class="button secondary seller-external-configure">Use external endpoint</button></details><details><summary>Self-hosted connector process (advanced)</summary><button type="button" class="button secondary seller-connector-issue">Create or rotate connector key</button><p class="seller-console-note">For sellers that operate their own connector process. Rotation immediately revokes the previous key.</p></details></div>` : "Verify email and wallet first";
  const onboardingBlockers = Array.isArray(onboarding.blockers) ? onboarding.blockers : [];
  const onboardingLabel = onboardingReview.status === "approved"
    ? "Approved independently by IAT Foundation"
    : onboardingReview.status === "blocked"
      ? `Independent review blocked: ${onboardingReview.decision || "foundation_review_required"}`
    : onboarding.status === "ready_for_foundation_review"
    ? "Evidence complete — independent Foundation review in progress"
    : `Evidence required: ${onboardingBlockers.join(", ") || "review pending"}`;
  const capabilityReviewLabel = Number(capabilityReconciliation.moved_to_review || 0) > 0
    ? `${capabilityReconciliation.moved_to_review} unapproved capability(s) safely moved to review`
    : "No unapproved active capability detected";
  panel.innerHTML = `<h3>Governance review</h3><p>Protocol approval remains independent from seller self-management.</p><div class="seller-governance-runtime"><span>Runtime state</span><strong>${escapeHtml(runtime.runtime_state || "pending review")}</strong></div><ul>${checks}<li><strong>Current onboarding evidence</strong><span>${escapeHtml(onboardingLabel)}</span></li><li><strong>Capability safety</strong><span>${escapeHtml(capabilityReviewLabel)}</span></li><li><strong>Seller status</strong><span>${escapeHtml(`${seller.seller_status || "pending"} / ${seller.verification_status || "unverified"}`)}</span></li><li><strong>Current email evidence</strong><span>${emailAction}</span></li><li><strong>Current wallet evidence</strong><span>${escapeHtml(walletEvidence)}</span></li><li><strong>Managed connector</strong><span>${connectorControl}</span></li><li><strong>Runtime reachability</strong><span>${escapeHtml(runtimeEvidence)}</span></li><li><strong>Advanced runtime control</strong><span><details><summary>Domain-controlled runtime</summary>${runtimeControl}</details></span></li>${autonomousRows}</ul>${autonomous.some((item) => item.status === "completed") ? '<p class="seller-console-note">Historical reviews preserve the evidence and policy snapshot used at decision time. Current evidence is shown separately above.</p>' : ""}`;
  panel.querySelector(".seller-verify-email")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Sending…";
    try {
      const result = await sandboxRequest("/seller/email-verification/request", { method: "POST", headers: sellerSessionHeaders });
      if (result.status !== "ok" && result.status !== "already_verified") throw new Error(result.message || "email_verification_failed");
      button.textContent = result.status === "already_verified" ? "Verified" : "Check your inbox";
    } catch (error) {
      button.disabled = false;
      button.textContent = `Retry: ${error.message}`;
    }
  });
  panel.querySelector(".seller-runtime-challenge")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const container = button.closest(".seller-runtime-verification");
    const runtimeUrl = container.querySelector(".seller-runtime-url").value.trim();
    const instructions = container.querySelector(".seller-runtime-instructions");
    const confirm = container.querySelector(".seller-runtime-confirm");
    button.disabled = true;
    try {
      const result = await sandboxRequest("/seller/runtime-verification/challenge", { method: "POST", headers: { "Content-Type": "application/json", ...sellerSessionHeaders }, body: JSON.stringify({ runtime_url: runtimeUrl }) });
      if (result.status !== "ok") {
        if (result.message === "shared_iat_runtime_cannot_prove_seller_control") throw new Error("Use a runtime domain controlled by this seller, not the shared IAT demo runtime");
        throw new Error(result.message || "runtime_challenge_failed");
      }
      instructions.textContent = `Publish this JSON at ${result.verification_url}:\n${JSON.stringify(result.document, null, 2)}`;
      instructions.hidden = false;
      confirm.hidden = false;
      button.textContent = "Challenge created";
    } catch (error) {
      button.disabled = false;
      button.textContent = `Retry: ${error.message}`;
    }
  });
  panel.querySelector(".seller-connector-issue")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const output = button.closest(".seller-connector-control").querySelector(".seller-connector-key");
    if (!window.confirm("Rotate the managed connector key? Any previous connector will stop immediately.")) return;
    button.disabled = true;
    try {
      const result = await sandboxRequest("/seller/connector/credentials/rotate", { method: "POST", headers: sellerSessionHeaders });
      if (result.status !== "ok" || !result.connector_key) throw new Error(result.message || "connector_key_failed");
      output.textContent = `Save this key now:\n${result.connector_key}\n\nImage: molamoh/iat-managed-seller-connector:latest`;
      output.hidden = false;
      button.textContent = "Rotate connector key";
    } catch (error) {
      button.disabled = false;
      button.textContent = `Retry: ${error.message}`;
    }
  });
  if (emailVerified && walletVerified) {
    sandboxRequest("/seller/connector/hosted/status", { headers: sellerSessionHeaders }).then((hosted) => {
      if (hosted.status !== "ok") return;
      const container = panel.querySelector(".seller-connector-control");
      const input = container?.querySelector(".seller-hosted-agent-url");
      const output = container?.querySelector(".seller-connector-key");
      if (input && hosted.agent_url) input.value = hosted.agent_url;
      if (output) {
        output.textContent = hosted.last_error
          ? `Hosted connector active. Last error: ${hosted.last_error}`
          : hosted.last_success_at
            ? `Hosted connector active. Last success: ${new Date(hosted.last_success_at * 1000).toLocaleString()}`
            : `${hosted.execution_mode === "iat_hosted" ? "IAT-hosted runtime" : "External endpoint"} configured and waiting for its first task.`;
        output.hidden = false;
      }
    }).catch(() => {});
  }
  panel.querySelector(".seller-hosted-configure")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const container = button.closest(".seller-connector-control");
    const output = container.querySelector(".seller-connector-key");
    button.disabled = true;
    button.textContent = "Enabling…";
    try {
      const result = await sandboxRequest("/seller/connector/hosted/configure", { method: "POST", headers: { "Content-Type": "application/json", ...sellerSessionHeaders }, body: JSON.stringify({ execution_mode: "iat_hosted" }) });
      if (result.status !== "ok") throw new Error(result.message || "hosted_connector_configuration_failed");
      output.textContent = "IAT-hosted runtime active. You can test it now.";
      output.hidden = false;
      button.textContent = "IAT runtime enabled";
    } catch (error) {
      button.disabled = false;
      button.textContent = `Retry: ${error.message}`;
    }
  });
  panel.querySelector(".seller-external-configure")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const container = button.closest(".seller-connector-control");
    const agentUrl = container.querySelector(".seller-hosted-agent-url").value.trim();
    const agentSecret = container.querySelector(".seller-hosted-agent-secret").value;
    const output = container.querySelector(".seller-connector-key");
    button.disabled = true;
    try {
      const result = await sandboxRequest("/seller/connector/hosted/configure", { method: "POST", headers: { "Content-Type": "application/json", ...sellerSessionHeaders }, body: JSON.stringify({ execution_mode: "external_endpoint", agent_url: agentUrl, agent_secret: agentSecret || null }) });
      if (result.status !== "ok") throw new Error(result.message || "external_connector_configuration_failed");
      container.querySelector(".seller-hosted-agent-secret").value = "";
      output.textContent = `External endpoint connected: ${result.agent_url}.`;
      output.hidden = false;
      button.textContent = "External endpoint connected";
    } catch (error) {
      button.disabled = false;
      button.textContent = `Retry: ${error.message}`;
    }
  });
  panel.querySelector(".seller-connector-canary")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const output = button.closest(".seller-connector-control").querySelector(".seller-connector-key");
    button.disabled = true;
    button.textContent = "Testing…";
    try {
      const result = await sandboxRequest("/seller/connector/canary", { method: "POST", headers: sellerSessionHeaders });
      if (result.status !== "ok") throw new Error(result.message || "connector_canary_failed");
      output.textContent = `Canary queued: ${result.task_id}${result.idempotent_replay ? " (already queued in this 5-minute window)" : ""}. Keep the connector running; it will claim this task automatically.`;
      output.hidden = false;
      button.textContent = "Waiting for connector…";
      for (let attempt = 0; attempt < 20; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 3000));
        const status = await sandboxRequest(`/seller/connector/tasks/${encodeURIComponent(result.task_id)}/status`, { headers: sellerSessionHeaders });
        if (status.status !== "ok") throw new Error(status.message || "connector_canary_status_failed");
        output.textContent = `Canary ${status.task_status}: ${result.task_id}. Attempts: ${status.attempt_count}.`;
        if (status.completed) {
          button.textContent = "Connector verified";
          return;
        }
      }
      button.disabled = false;
      button.textContent = "Check connector again";
      output.textContent += " The connector did not claim the task within 60 seconds. Check that it is running with the current connector key.";
    } catch (error) {
      button.disabled = false;
      button.textContent = `Retry: ${error.message}`;
    }
  });
  panel.querySelector(".seller-runtime-confirm")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const result = await sandboxRequest("/seller/runtime-verification/confirm", { method: "POST", headers: sellerSessionHeaders });
      if (result.status !== "ok") throw new Error(result.message || "runtime_verification_failed");
      await refreshSellerConsole();
    } catch (error) {
      button.disabled = false;
      button.textContent = `Retry: ${error.message}`;
    }
  });
  const items = Array.isArray(recent.catalog_items) ? recent.catalog_items : [];
  const requests = Array.isArray(recent.factory_requests) ? recent.factory_requests : [];
  const capabilityCatalogSelector = (agent) => {
    const service = String(agent.service || "").toLowerCase();
    const eligible = items.filter((item) => ["verified", "foundation_verified"].includes(String(item.verification_status || "").toLowerCase()) && String(item.availability_status || "").toLowerCase() !== "archived");
    if (eligible.length <= 1) return "";
    return `<label>Catalog<select class="seller-agent-catalog"><option value="">Choose the matching catalog</option>${eligible.map((item) => `<option value="${escapeHtml(item.catalog_item_id)}">${escapeHtml(`${item.title || item.catalog_item_id} · ${item.service_type || service}`)}</option>`).join("")}</select></label>`;
  };
  const records = [...agents.map((agent) => `<li>Capability <code>${escapeHtml(agent.seller_agent_id || "unknown")}</code><span>${escapeHtml(agent.seller_agent_status || "unknown")}</span>${agent.seller_agent_status === "pending_review" ? `${capabilityCatalogSelector(agent)}<button type="button" class="button secondary seller-review-agent" data-agent-id="${escapeHtml(agent.seller_agent_id || "")}">Review &amp; activate</button>` : ""}${agent.seller_agent_status === "disabled" ? "" : `<button type="button" class="button secondary seller-disable-agent" data-agent-id="${escapeHtml(agent.seller_agent_id || "")}">Disable</button>`}</li>`), ...items.map((item) => `<li>Catalog <code>${escapeHtml(item.catalog_item_id || "unknown")}</code><span>${escapeHtml(item.verification_status || "unverified")}</span>${item.availability_status === "archived" ? "<span>archived</span>" : `${!["verified", "foundation_verified"].includes(String(item.verification_status || "").toLowerCase()) ? `<button type="button" class="button secondary seller-review-catalog" data-catalog-id="${escapeHtml(item.catalog_item_id || "")}">Request review</button>` : ""}<button type="button" class="button secondary seller-archive-catalog" data-catalog-id="${escapeHtml(item.catalog_item_id || "")}">Archive</button>`}</li>`), ...requests.map((item) => `<li>Review <code>${escapeHtml(item.factory_request_id || "unknown")}</code><span>${escapeHtml(item.governance_status || "unknown")}</span></li>`)];
  if (records.length) panel.insertAdjacentHTML("beforeend", `<h4>Your server records</h4><ul>${records.join("")}</ul>`);
  panel.querySelectorAll(".seller-review-catalog").forEach((button) => button.addEventListener("click", async () => {
    const catalogId = button.dataset.catalogId;
    if (!catalogId || !sellerSessionHeaders) return;
    button.disabled = true;
    button.textContent = "Reviewing…";
    try {
      const result = await sandboxRequest(`/seller/catalog/items/${encodeURIComponent(catalogId)}/request-review`, { method: "POST", headers: sellerSessionHeaders });
      if (result.status !== "approved") throw new Error((result.review?.failed_checks || [result.message || "catalog_review_rejected"]).join(", "));
      await refreshSellerConsole();
    } catch (error) {
      button.disabled = false;
      button.textContent = `Rejected: ${error.message}`;
    }
  }));
  panel.querySelectorAll(".seller-review-agent").forEach((button) => button.addEventListener("click", async () => {
    const agentId = button.dataset.agentId;
    if (!agentId || !sellerSessionHeaders) return;
    const catalogId = button.closest("li")?.querySelector(".seller-agent-catalog")?.value || "";
    if (button.closest("li")?.querySelector(".seller-agent-catalog") && !catalogId) {
      button.textContent = "Choose a catalog first";
      return;
    }
    button.disabled = true;
    button.textContent = "Reviewing…";
    try {
      const catalogQuery = catalogId ? `?catalog_item_id=${encodeURIComponent(catalogId)}` : "";
      const result = await sandboxRequest(`/seller/agents/${encodeURIComponent(agentId)}/request-review${catalogQuery}`, { method: "POST", headers: sellerSessionHeaders });
      if (result.status !== "approved") {
        const reasons = result.evidence?.failed_checks || [];
        throw new Error(reasons.length ? reasons.join(", ") : result.approval?.message || result.message || "capability_review_blocked");
      }
      await refreshSellerConsole();
    } catch (error) {
      button.disabled = false;
      button.textContent = `Blocked: ${error.message}`;
    }
  }));
  panel.querySelectorAll(".seller-archive-catalog").forEach((button) => button.addEventListener("click", async () => {
    const catalogId = button.dataset.catalogId;
    if (!catalogId || !sellerSessionHeaders || !window.confirm("Archive this catalog listing? Existing orders remain preserved.")) return;
    button.disabled = true;
    try {
      const result = await sandboxRequest(`/seller/catalog/items/${encodeURIComponent(catalogId)}/archive?reason=seller_console_archive`, { method: "POST", headers: sellerSessionHeaders });
      if (result.status !== "ok") throw new Error(result.message || "archive_rejected");
      await refreshSellerConsole();
    } catch (error) {
      button.disabled = false;
      window.alert(`Unable to archive listing: ${error.message}`);
    }
  }));
  panel.querySelectorAll(".seller-disable-agent").forEach((button) => button.addEventListener("click", async () => {
    const agentId = button.dataset.agentId;
    if (!agentId || !sellerSessionHeaders || !window.confirm("Disable this capability and release its capacity slot?")) return;
    button.disabled = true;
    try {
      const result = await sandboxRequest(`/seller/agents/${encodeURIComponent(agentId)}/disable?reason=seller_console_disable`, { method: "POST", headers: sellerSessionHeaders });
      if (result.status !== "ok") throw new Error(result.message || "disable_rejected");
      await refreshSellerConsole();
    } catch (error) { button.disabled = false; window.alert(`Unable to disable capability: ${error.message}`); }
  }));
}

async function refreshSellerConsole() {
  if (!sellerSessionHeaders) return;
  // Opening the console must remain a bounded read. Governance is advanced by
  // the explicit review actions below, not by this dashboard refresh.
  const dashboard = await sandboxRequest("/seller/dashboard?advance_governance=false", { headers: sellerSessionHeaders });
  const [analyticsResult, payoutsResult] = await Promise.allSettled([
    sandboxRequest("/seller/analytics", { headers: sellerSessionHeaders }),
    sandboxRequest("/seller/payouts", { headers: sellerSessionHeaders }),
  ]);
  if (dashboard.status !== "ok") throw new Error(dashboard.message || "seller_dashboard_unavailable");
  const analytics = analyticsResult.status === "fulfilled"
    ? analyticsResult.value
    : { status: "temporarily unavailable" };
  const payouts = payoutsResult.status === "fulfilled"
    ? payoutsResult.value
    : { status: "temporarily unavailable" };
  const sellerState = dashboard.seller || {};
  const agentCounts = dashboard.summary?.agent_status_counts || {};
  const capabilityCount = Object.values(agentCounts).reduce((total, count) => total + Number(count || 0), 0);
  document.querySelector("#seller-console-seller").textContent = `${sellerState.seller_status || "unknown"} / ${sellerState.verification_status || "unverified"}`;
  document.querySelector("#seller-console-analytics").textContent = `${analytics.status || "available"} · ${capabilityCount} capability(ies)`;
  document.querySelector("#seller-console-payouts").textContent = payouts.status || "available";
  sellerConsoleResult.hidden = false;
  renderSellerGovernanceState(dashboard);
}

function installSellerCatalogForm() {
  const card = document.querySelector(".seller-console-card");
  if (!card || document.querySelector("#seller-catalog-create")) return;
  const details = document.createElement("details");
  details.className = "seller-capability-form";
  details.innerHTML = `<summary>Create catalog listing and request agent review</summary><p class="inbox-help">This creates the commercial record required by governance. It does not approve or expose the seller.</p><label>Listing title<input id="seller-catalog-title" placeholder="Verified web research"></label><label>Category<input id="seller-catalog-category" value="ai_service"></label><label>Description<textarea id="seller-catalog-description" rows="3" placeholder="Describe the result delivered to the buyer."></textarea></label><label>Service type<input id="seller-catalog-service" value="web_research"></label><label>Unit price in IAT<input id="seller-catalog-price" value="1.00" inputmode="decimal"></label><label>Maximum orders per day<input id="seller-catalog-capacity" value="10" inputmode="numeric" min="1"></label><button id="seller-catalog-create" class="button primary" type="button">Create catalog listing</button><p id="seller-catalog-status" class="seller-status" role="status" aria-live="polite"></p><div id="seller-factory-followup" hidden><label>Agent review prompt<textarea id="seller-factory-prompt" rows="3">Validate this seller capability against the declared runtime and delivery terms.</textarea></label><button id="seller-factory-request" class="button secondary" type="button">Request protocol agent review</button></div>`;
  const savedArtifacts = (() => { try { return JSON.parse(localStorage.getItem("iat_seller_artifacts") || "{}"); } catch (_) { return {}; } })();
  const artifactPanel = document.createElement("div");
  artifactPanel.className = "seller-artifacts";
  artifactPanel.innerHTML = `<strong>Your IAT records</strong><span>Catalog listing: <code>${savedArtifacts.catalog_item_id || "—"}</code></span><span>Governance review: <code>${savedArtifacts.governance_review_id || "—"}</code></span>`;
  details.append(artifactPanel);
  bindDraft("seller-catalog", [details.querySelector("#seller-catalog-title"), details.querySelector("#seller-catalog-category"), details.querySelector("#seller-catalog-description"), details.querySelector("#seller-catalog-service"), details.querySelector("#seller-catalog-price"), details.querySelector("#seller-catalog-capacity"), details.querySelector("#seller-factory-prompt")]);
  card.append(details);
  const status = details.querySelector("#seller-catalog-status");
  details.querySelector("#seller-catalog-create").addEventListener("click", async () => {
    if (!sellerSessionHeaders) { status.className = "seller-status error"; status.textContent = "Open the private console first."; return; }
    const payload = { item_type: "service", category: details.querySelector("#seller-catalog-category").value.trim(), title: details.querySelector("#seller-catalog-title").value.trim(), description: details.querySelector("#seller-catalog-description").value.trim(), service_type: details.querySelector("#seller-catalog-service").value.trim(), unit_price: Number(details.querySelector("#seller-catalog-price").value.trim()), currency: "IAT", availability_status: "active", capacity_per_day: Number(details.querySelector("#seller-catalog-capacity").value.trim()), capacity_per_order: 1 };
    if (!payload.title || payload.description.length < 20 || !payload.category || !payload.service_type || !Number.isFinite(payload.unit_price) || payload.unit_price <= 0 || !Number.isFinite(payload.capacity_per_day) || payload.capacity_per_day <= 0) { status.className = "seller-status error"; status.textContent = "Complete every field; use a description of at least 20 characters, a positive price and a positive daily capacity."; return; }
    const button = details.querySelector("#seller-catalog-create"); button.disabled = true; status.className = "seller-status"; status.textContent = "Creating catalog listing…";
    try {
      const result = await sandboxRequest("/seller/catalog/items", { method: "POST", headers: { "Content-Type": "application/json", ...sellerSessionHeaders }, body: JSON.stringify(payload) });
      const item = result.catalog_item;
      if (result.status !== "ok" || !item?.catalog_item_id) throw new Error(result.message || "catalog_creation_rejected");
      details.dataset.catalogItemId = item.catalog_item_id; savedArtifacts.catalog_item_id = item.catalog_item_id; localStorage.setItem("iat_seller_artifacts", JSON.stringify(savedArtifacts)); artifactPanel.querySelectorAll("code")[0].textContent = item.catalog_item_id; details.querySelector("#seller-factory-followup").hidden = false; status.className = "seller-status success"; status.textContent = `Catalog listing created: ${item.catalog_item_id}. Request the governance review below.`; await refreshSellerConsole(); trackFunnel("seller-catalog-created");
    } catch (error) { status.className = "seller-status error"; status.textContent = `Unable to create listing: ${error.message}`; }
    finally { button.disabled = false; }
  });
  details.querySelector("#seller-factory-request").addEventListener("click", async () => {
    const catalogItemId = details.dataset.catalogItemId;
    if (!catalogItemId || !sellerSessionHeaders) { status.className = "seller-status error"; status.textContent = "Create the catalog listing and open the console first."; return; }
    const button = details.querySelector("#seller-factory-request"); button.disabled = true; status.className = "seller-status"; status.textContent = "Submitting review request…";
    try { const result = await sandboxRequest("/seller/agent-factory/requests", { method: "POST", headers: { "Content-Type": "application/json", ...sellerSessionHeaders }, body: JSON.stringify({ catalog_item_id: catalogItemId, requested_agent_name: details.querySelector("#seller-catalog-title").value.trim(), requested_prompt: details.querySelector("#seller-factory-prompt").value.trim(), requested_agent_count: 1 }) }); if (result.status !== "ok") throw new Error(result.message || "factory_request_rejected"); const requestId = result.factory_request_id || result.factory_request?.factory_request_id || "submitted"; savedArtifacts.governance_review_id = requestId; localStorage.setItem("iat_seller_artifacts", JSON.stringify(savedArtifacts)); artifactPanel.querySelectorAll("code")[1].textContent = requestId; status.className = "seller-status success"; status.textContent = `Governance review requested: ${requestId}.`; await refreshSellerConsole(); trackFunnel("seller-factory-review-requested"); } catch (error) { status.className = "seller-status error"; status.textContent = `Unable to request review: ${error.message}`; } finally { button.disabled = false; }
  });
}

async function authenticateSellerWallet() {
  const selected = Number(walletSelector.value);
  const wallet = discoveredWallets[selected];
  if (!wallet) throw new Error("Select a detected Wallet Standard-compatible Solana wallet first");
  let connection;
  try {
    connection = await wallet.features["standard:connect"].connect();
  } catch (error) {
    throw new Error(`wallet_connect_failed: ${error?.message || "wallet connection rejected"}`);
  }
  const account = connection?.accounts?.[0] || wallet.accounts?.[0];
  if (!account?.address) throw new Error("The wallet returned no Solana account");
  let challenge;
  try {
    challenge = await apiJson("/seller/wallet-auth/challenge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ wallet: account.address }),
    });
  } catch (error) {
    throw new Error(`challenge_request_failed: ${error?.message || "network request failed"}`);
  }
  let signed;
  try {
    signed = await wallet.features["solana:signMessage"].signMessage({
      account,
      message: new TextEncoder().encode(challenge.message),
    });
  } catch (error) {
    throw new Error(`wallet_signature_failed: ${error?.message || "signature rejected"}`);
  }
  const signature = signed?.[0]?.signature;
  if (!signature) throw new Error("The wallet returned no message signature");
  try {
    return await apiJson("/seller/wallet-auth/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ challenge_id: challenge.challenge_id, signature: base58Encode(signature) }),
    });
  } catch (error) {
    throw new Error(`session_exchange_failed: ${error?.message || "network request failed"}`);
  }
}

sellerRegisterSubmit.addEventListener("click", async () => {
  const payload = {
    seller_name: sellerRegisterName.value.trim(),
    seller_kind: "ai_agent",
    wallet: sellerRegisterWallet.value.trim(),
    email: sellerRegisterEmail.value.trim(),
    website: sellerRegisterWebsite.value.trim() || null,
  };
  if (!payload.seller_name || payload.wallet.length < 8 || !payload.email) {
    sellerRegisterStatus.className = "seller-status error";
    sellerRegisterStatus.textContent = "Enter a seller name, public wallet and business email.";
    return;
  }
  sellerRegisterSubmit.disabled = true;
  sellerRegisterStatus.className = "seller-status";
  sellerRegisterStatus.textContent = "Creating seller account…";
  try {
    const result = await sandboxRequest("/seller/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!result.api_key) throw new Error(result.message || "Registration did not return a key");
    sellerRegisterKeyValue.textContent = result.api_key;
    sellerRegisterKey.hidden = false;
    sellerApiKey.value = result.api_key;
    sellerRegisterStatus.className = "seller-status success";
    sellerRegisterStatus.textContent = "Account created pending protocol review. Save the key, then open the seller console.";
    trackFunnel("seller-registered");
  } catch (error) {
    sellerRegisterStatus.className = "seller-status error";
    sellerRegisterStatus.textContent = `Unable to register: ${error.message}`;
  } finally {
    sellerRegisterSubmit.disabled = false;
  }
});

sellerConsoleOpen.addEventListener("click", async () => {
  const key = sellerApiKey.value.trim();
  sellerConsoleOpen.disabled = true;
  sellerConsoleStatus.className = "seller-status";
  sellerConsoleStatus.textContent = key.length >= 16
    ? "Authenticating seller console with API key…"
    : "Review the wallet message: authentication only, no transaction or payment.";
  try {
    const session = key.length >= 16 ? null : await authenticateSellerWallet();
    const headers = session
      ? { Authorization: `Bearer ${session.access_token}` }
      : { "X-Seller-API-Key": key };
    sellerSessionHeaders = headers;
    try {
      if (session?.access_token) sessionStorage.setItem("iat_seller_access_token", session.access_token);
      if (key) sessionStorage.setItem("iat_seller_api_key", key);
    } catch (_) { /* memory-only fallback */ }
    try {
      await refreshSellerConsole();
    } catch (error) {
      throw new Error(`console_data_failed: ${error?.message || "network request failed"}`);
    }
    sellerConsoleStatus.className = "seller-status success";
    sellerConsoleStatus.textContent = "Seller console ready for this browser session.";
    trackFunnel("seller-console-opened");
  } catch (error) {
    sellerConsoleStatus.className = "seller-status error";
    sellerConsoleStatus.textContent = `Unable to open console: ${error.message}`;
  } finally {
    sellerConsoleOpen.disabled = false;
  }
});

form.addEventListener("focusin", () => trackFunnel("form-started"), { once: true });

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!form.reportValidity()) return;

  const submit = form.querySelector("button[type=submit]");
  const data = new FormData(form);
  const payload = Object.fromEntries(data.entries());
  payload.outreach_opt_in = data.get("outreach_opt_in") === "on";
  submit.disabled = true;
  status.className = "form-status";
  status.textContent = "Submitting your application…";

  try {
    const response = await fetch(`${API_BASE}/growth/v1/pilot`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Application rejected");
    trackFunnel("application-accepted");
    status.className = "form-status success";
    status.textContent = result.status === "already_registered"
      ? `Already registered. Pilot ID: ${result.pilot_id}`
      : `Application accepted. Pilot ID: ${result.pilot_id}`;
    if (result.status !== "already_registered") form.reset();
  } catch (error) {
    trackFunnel("application-error");
    status.className = "form-status error";
    status.textContent = `Unable to submit: ${error.message}. You can still use the public API directly.`;
  } finally {
    submit.disabled = false;
  }
});

let walletSelector = optionalElement("#wallet-selector");
const walletConnect = optionalElement("#wallet-connect");
const walletRefresh = optionalElement("#wallet-refresh");
const walletDisconnect = optionalElement("#wallet-disconnect");
const walletConnectPanel = optionalElement("#wallet-connect-panel");
const walletSessionPanel = optionalElement("#wallet-session-panel");
const walletAddress = optionalElement("#wallet-address");
const inboxStatus = optionalElement("#inbox-status");
const inboxResults = optionalElement("#inbox-results");
const inboxItems = optionalElement("#inbox-items");
const inboxCount = optionalElement("#inbox-count");
const inboxMore = optionalElement("#inbox-more");
const walletCheckout = optionalElement("#wallet-checkout");
const checkoutOrderId = optionalElement("#checkout-order-id");
bindDraft("buyer-checkout", [checkoutOrderId]);
const checkoutPrepare = optionalElement("#checkout-prepare");
const checkoutReview = optionalElement("#checkout-review");
const checkoutSend = optionalElement("#checkout-send");
const usagePrepare = optionalElement("#usage-prepare");
const usageReview = optionalElement("#usage-review");
const usageSend = optionalElement("#usage-send");

// Seller pages do not need the buyer inbox markup, but wallet sign-in still
// needs a visible choice when several browser wallets are installed.
if (!document.querySelector("#wallet-selector")) {
  const sellerCard = document.querySelector(".seller-console-card");
  if (sellerCard) {
    const label = document.createElement("label");
    label.htmlFor = "wallet-selector";
    label.textContent = "Detected Solana wallet";
    const select = document.createElement("select");
    select.id = "wallet-selector";
    select.innerHTML = '<option value="">Detecting wallets…</option>';
    label.append(select);
    sellerCard.insertBefore(label, sellerCard.firstChild);
    walletSelector = select;
  }
}
installSellerCapabilityForm();
installSellerCatalogForm();
const discoveredWallets = [];
const registeredLegacyProviders = new WeakSet();
let activeWallet = null;
let activeAccount = null;
let inboxCursor = null;
let displayedDeliveries = 0;
let preparedCheckout = null;
let preparedUsageInitialization = null;
const PENDING_CHECKOUT_KEY = "iat_pending_checkout_v1";
const PENDING_CHECKOUT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
let volatilePendingCheckout = null;

function sessionGet(key) {
  try { return sessionStorage.getItem(key); } catch (_) { return null; }
}

function sessionSet(key, value) {
  try { sessionStorage.setItem(key, value); } catch (_) { /* memory-only fallback */ }
}

function readPendingCheckout() {
  try {
    const pending = JSON.parse(localStorage.getItem(PENDING_CHECKOUT_KEY) || "null");
    const valid = pending
      && /^[1-9A-HJ-NP-Za-km-z]{64,128}$/.test(pending.tx_signature || "")
      && /^uq_[a-f0-9]{32}$/.test(pending.quote_id || "")
      && /^[a-f0-9-]{36}$/i.test(pending.order_id || "")
      && typeof pending.wallet === "string"
      && Number.isFinite(pending.saved_at)
      && Date.now() - pending.saved_at <= PENDING_CHECKOUT_MAX_AGE_MS;
    if (valid) return pending;
    localStorage.removeItem(PENDING_CHECKOUT_KEY);
  } catch (_) { /* invalid or unavailable durable storage */ }
  return volatilePendingCheckout;
}

function savePendingCheckout(pending) {
  volatilePendingCheckout = pending;
  try {
    localStorage.setItem(PENDING_CHECKOUT_KEY, JSON.stringify(pending));
    return true;
  } catch (_) { return false; }
}

function clearPendingCheckout(quoteId) {
  const pending = readPendingCheckout();
  if (!pending || pending.quote_id !== quoteId) return;
  volatilePendingCheckout = null;
  try { localStorage.removeItem(PENDING_CHECKOUT_KEY); } catch (_) { /* confirmed server-side */ }
}

function clearInboxSession() {
  try {
    sessionStorage.removeItem("iat_inbox_token");
    sessionStorage.removeItem("iat_inbox_wallet");
  } catch (_) { /* already cleared */ }
}

function setInboxStatus(message, type = "") {
  inboxStatus.className = `inbox-status${type ? ` ${type}` : ""}`;
  inboxStatus.textContent = message;
}

function shortAddress(address) {
  return `${address.slice(0, 5)}…${address.slice(-5)}`;
}

function registerWallets(...wallets) {
  for (const wallet of wallets) {
    const canConnect = wallet?.features?.["standard:connect"];
    const canSign = wallet?.features?.["solana:signMessage"];
    if (canConnect && canSign && !discoveredWallets.includes(wallet)) {
      discoveredWallets.push(wallet);
    }
  }
  renderWalletOptions();
  return () => {
    for (const wallet of wallets) {
      const index = discoveredWallets.indexOf(wallet);
      if (index >= 0) discoveredWallets.splice(index, 1);
    }
    renderWalletOptions();
  };
}

function renderWalletOptions() {
  walletSelector.replaceChildren();
  if (!discoveredWallets.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No compatible wallet detected";
    walletSelector.append(option);
    walletConnect.disabled = true;
    setInboxStatus("Install or unlock a Wallet Standard-compatible Solana wallet.", "error");
    return;
  }
  discoveredWallets.forEach((wallet, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = wallet.name || `Solana wallet ${index + 1}`;
    walletSelector.append(option);
  });
  walletConnect.disabled = false;
  if (!sessionGet("iat_inbox_token")) setInboxStatus("Ready. Connecting will request one authentication signature.");
}

function installWalletStandardDiscovery() {
  const api = Object.freeze({ register: registerWallets });
  window.addEventListener("wallet-standard:register-wallet", (event) => {
    if (typeof event.detail === "function") event.detail(api);
  });
  window.dispatchEvent(new CustomEvent("wallet-standard:app-ready", { detail: api }));
  scanInjectedWallets();
  [250, 750, 1500, 3000, 6000].forEach((delay) => window.setTimeout(scanInjectedWallets, delay));
  window.addEventListener("focus", scanInjectedWallets);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") scanInjectedWallets();
  });
}

function registerLegacyProvider(provider, name) {
  if (!provider || typeof provider !== "object" || registeredLegacyProviders.has(provider)) return;
  if (typeof provider.connect !== "function" || typeof provider.signMessage !== "function") return;
  if (discoveredWallets.some((wallet) => String(wallet.name || "").toLowerCase().includes(name.toLowerCase()))) return;
  registeredLegacyProviders.add(provider);
  registerWallets({
    name: `${name} (browser wallet)`,
    accounts: [],
    features: {
      "standard:connect": { connect: async () => {
        const result = await provider.connect();
        const publicKey = result?.publicKey || provider.publicKey;
        if (!publicKey) throw new Error(`${name} returned no public key`);
        return { accounts: [{ address: publicKey.toString() }] };
      } },
      "standard:disconnect": { disconnect: async () => {
        if (typeof provider.disconnect === "function") await provider.disconnect();
      } },
      "solana:signMessage": { signMessage: async ({ message }) => {
        const result = await provider.signMessage(message, "utf8");
        const signature = result?.signature || result;
        return [{ signature }];
      } },
    },
  });
}

function scanInjectedWallets() {
  const candidates = [
    [window.phantom?.solana, "Phantom"],
    [window.solflare, "Solflare"],
    [window.backpack?.solana, "Backpack"],
    [window.xnft?.solana, "Backpack"],
    [window.coinbaseSolana, "Coinbase Wallet"],
    [window.okxwallet?.solana, "OKX Wallet"],
    [window.trustwallet?.solana, "Trust Wallet"],
    [window.exodus?.solana, "Exodus"],
    [window.solana, window.solana?.isPhantom ? "Phantom" : "Solana wallet"],
  ];
  for (const [provider, name] of candidates) registerLegacyProvider(provider, name);
  if (!discoveredWallets.length) {
    setInboxStatus(
      "No wallet was injected into this page. On mobile, open iatprotocol.com inside Phantom's Browser tab—not in Chrome, Safari or WhatsApp.",
      "error",
    );
  }
}

function base58Encode(value) {
  const bytes = value instanceof Uint8Array ? value : new Uint8Array(value);
  const alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
  if (!bytes.length) return "";
  const digits = [0];
  for (const byte of bytes) {
    let carry = byte;
    for (let index = 0; index < digits.length; index += 1) {
      carry += digits[index] << 8;
      digits[index] = carry % 58;
      carry = Math.floor(carry / 58);
    }
    while (carry > 0) {
      digits.push(carry % 58);
      carry = Math.floor(carry / 58);
    }
  }
  let leadingZeroes = 0;
  while (leadingZeroes < bytes.length - 1 && bytes[leadingZeroes] === 0) leadingZeroes += 1;
  let encoded = "1".repeat(leadingZeroes);
  for (let index = digits.length - 1; index >= 0; index -= 1) encoded += alphabet[digits[index]];
  return encoded;
}

async function apiJson(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  let payload = {};
  try { payload = await response.json(); } catch (_) { /* HTTP status is enough */ }
  if (!response.ok) {
    const detail = typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`;
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return payload;
}

async function authenticateSelectedWallet() {
  const selected = Number(walletSelector.value);
  const wallet = discoveredWallets[selected];
  if (!wallet) throw new Error("Select a compatible Solana wallet");
  const connection = await wallet.features["standard:connect"].connect();
  const account = connection?.accounts?.[0] || wallet.accounts?.[0];
  if (!account?.address) throw new Error("The wallet returned no Solana account");

  activeWallet = wallet;
  activeAccount = account;
  setInboxStatus("Review the wallet prompt: authentication only, no transaction or payment.");
  const challenge = await apiJson("/payments/v1/universal/wallet-auth/challenge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ wallet: account.address }),
  });
  const message = new TextEncoder().encode(challenge.message);
  const signed = await wallet.features["solana:signMessage"].signMessage({ account, message });
  const signature = signed?.[0]?.signature;
  if (!signature) throw new Error("The wallet returned no message signature");
  const session = await apiJson("/payments/v1/universal/wallet-auth/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ challenge_id: challenge.challenge_id, signature: base58Encode(signature) }),
  });
  sessionSet("iat_inbox_token", session.access_token);
  sessionSet("iat_inbox_wallet", session.wallet);
  showAuthenticatedWallet(session.wallet);
  await resumePendingCheckout();
  try {
    await apiJson("/payments/v1/universal/wallet-checkout/recover-submitted", {
      method: "POST",
      headers: { Authorization: `Bearer ${session.access_token}` },
    });
  } catch (error) {
    if (error.status === 401) throw error;
  }
  await loadInbox(true);
  const pending = readPendingCheckout();
  if (pending?.wallet === session.wallet) {
    setInboxStatus(`Authenticated. Payment ${shortAddress(pending.tx_signature)} remains saved for automatic recovery.`, "success");
  }
}

function showAuthenticatedWallet(address) {
  walletConnectPanel.hidden = true;
  walletSessionPanel.hidden = false;
  walletAddress.textContent = shortAddress(address);
  walletAddress.title = address;
  walletCheckout.hidden = false;
  loadBuyerDashboard().catch(() => {});
}

async function loadBuyerDashboard() {
  const token = sessionGet("iat_inbox_token");
  if (!token || !walletCheckout || walletCheckout.hidden) return;
  let panel = document.querySelector("#buyer-dashboard-summary");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "buyer-dashboard-summary";
    panel.className = "checkout-review";
    walletCheckout.insertBefore(panel, walletCheckout.firstChild);
  }
  panel.hidden = false;
  panel.textContent = "Loading buyer account…";
  const dashboard = await apiJson("/buyer/dashboard", { headers: { Authorization: `Bearer ${token}` } });
  const counts = dashboard.summary?.delivery_status_counts || {};
  const countText = Object.entries(counts).map(([state, count]) => `${state}: ${count}`).join(" · ") || "No deliveries yet";
  panel.innerHTML = `<strong>Buyer account</strong><span>${dashboard.summary?.delivery_count || 0} delivery receipt(s)</span><small>${countText}</small>`;
}

function base64Bytes(value) {
  const binary = atob(value);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function amountLabel(asset) {
  return `${asset?.amount || "?"} ${asset?.symbol || asset?.asset || ""}`.trim();
}

function setReviewText(id, value) {
  document.querySelector(id).textContent = String(value || "Not provided");
}

async function ensureActiveWalletConnection() {
  if (activeWallet && activeAccount) return;
  const wallet = discoveredWallets[Number(walletSelector.value)];
  if (!wallet) throw new Error("Select Phantom and reconnect it to this page");
  const connection = await wallet.features["standard:connect"].connect();
  const account = connection?.accounts?.[0] || wallet.accounts?.[0];
  if (!account?.address || account.address !== sessionGet("iat_inbox_wallet")) {
    throw new Error("Phantom is connected to a different wallet than this inbox session");
  }
  activeWallet = wallet;
  activeAccount = account;
}

async function prepareUsageInitialization() {
  const token = sessionGet("iat_inbox_token");
  if (!token) throw new Error("Connect your wallet again");
  setInboxStatus("Checking the GN2d first-purchase account and simulating initialization…");
  const result = await apiJson("/payments/v1/universal/wallet-checkout/initialize", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (result.status === "wallet_usage_already_initialized") {
    preparedUsageInitialization = null;
    usageReview.hidden = true;
    setInboxStatus("GN2d buyer account is already initialized. You can prepare the USDC payment.", "success");
    return;
  }
  preparedUsageInitialization = result;
  setReviewText("#usage-network", result.review.cluster);
  setReviewText("#usage-program", result.review.program_id);
  setReviewText("#usage-fee-payer", result.review.fee_payer);
  setReviewText("#usage-account", result.review.wallet_usage);
  setReviewText("#usage-simulation", `${result.review.simulation} (${result.review.units_consumed || "unknown"} units)`);
  usageReview.hidden = false;
  setInboxStatus("Initialization simulation succeeded. Review the fields before opening Phantom.", "success");
}

async function sendUsageInitialization() {
  if (!preparedUsageInitialization) throw new Error("Check the first-purchase setup again");
  await ensureActiveWalletConnection();
  const feature = activeWallet.features?.["solana:signAndSendTransaction"];
  if (!feature?.signAndSendTransaction) throw new Error("Reconnect through Phantom's in-app Browser");
  setInboxStatus("Waiting for your initialization approval in Phantom. No token transfer is included.");
  const result = await feature.signAndSendTransaction({
    account: activeAccount,
    chain: "solana:devnet",
    transaction: base64Bytes(preparedUsageInitialization.transaction_base64),
    options: { commitment: "confirmed" },
  });
  const signature = result?.[0]?.signature;
  if (!signature) throw new Error("Phantom returned no transaction signature");
  setInboxStatus(`Initialization sent: ${shortAddress(base58Encode(signature))}. Waiting for devnet…`);
  await new Promise((resolve) => window.setTimeout(resolve, 3500));
  preparedUsageInitialization = null;
  usageReview.hidden = true;
  await prepareUsageInitialization();
}

async function prepareCheckout() {
  const orderId = checkoutOrderId.value.trim();
  const token = sessionGet("iat_inbox_token");
  if (!/^[a-f0-9-]{36}$/i.test(orderId)) throw new Error("Enter a valid IAT order ID");
  if (!token) throw new Error("Connect your wallet again");
  setInboxStatus("Creating a fresh quote, obtaining IAT authorization and simulating on devnet…");
  preparedCheckout = await apiJson(`/payments/v1/universal/wallet-checkout/${encodeURIComponent(orderId)}/prepare`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ input_asset: "USDC" }),
  });
  const review = preparedCheckout.review;
  setReviewText("#checkout-network", review.cluster);
  setReviewText("#checkout-input", amountLabel(review.input));
  setReviewText("#checkout-output", amountLabel(review.minimum_iat_output));
  setReviewText("#checkout-fee-payer", review.fee_payer);
  setReviewText("#checkout-vault", review.treasury_vault);
  setReviewText("#checkout-simulation", `${preparedCheckout.simulation.status} (${preparedCheckout.simulation.units_consumed || "unknown"} units)`);
  checkoutReview.hidden = false;
  setInboxStatus("Simulation succeeded. Review every field before confirming in Phantom.", "success");
}

async function confirmCheckoutInWallet() {
  if (!preparedCheckout) throw new Error("Prepare a fresh payment first");
  await ensureActiveWalletConnection();
  const feature = activeWallet.features?.["solana:signAndSendTransaction"];
  if (!feature?.signAndSendTransaction || !activeAccount) {
    throw new Error("This wallet connection cannot send Wallet Standard transactions. Reconnect using Phantom's in-app Browser.");
  }
  setInboxStatus("Waiting for your explicit approval in Phantom…");
  const result = await feature.signAndSendTransaction({
    account: activeAccount,
    chain: "solana:devnet",
    transaction: base64Bytes(preparedCheckout.transaction_base64),
    options: { commitment: "confirmed" },
  });
  const signatureBytes = result?.[0]?.signature;
  if (!signatureBytes) throw new Error("Phantom returned no transaction signature");
  const txSignature = base58Encode(signatureBytes);
  const pending = {
    wallet: activeAccount.address,
    order_id: preparedCheckout.order_id,
    quote_id: preparedCheckout.quote_id,
    tx_signature: txSignature,
    saved_at: Date.now(),
  };
  const durableRecovery = savePendingCheckout(pending);
  preparedCheckout = null;
  if (!durableRecovery) {
    setInboxStatus("Transaction sent. Keep this page open because durable browser recovery is unavailable.", "error");
  }
  await settlePendingCheckout(pending);
}

async function settlePendingCheckout(pending) {
  const token = sessionGet("iat_inbox_token");
  if (!token) throw new Error("Reconnect your wallet to resume the submitted payment");
  if (pending.wallet !== sessionGet("iat_inbox_wallet")) {
    throw new Error("A pending payment belongs to another wallet");
  }
  try {
    await apiJson(`/payments/v1/universal/wallet-checkout/${pending.quote_id}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ tx_signature: pending.tx_signature }),
    });
  } catch (error) {
    // A previous tab may already have submitted or confirmed this exact quote.
    // The confirm endpoint is idempotent and remains the source of truth.
    if (error.status !== 409) throw error;
  }
  setInboxStatus(`Transaction sent: ${shortAddress(pending.tx_signature)}. Waiting for devnet confirmation…`);
  for (let attempt = 0; attempt < 24; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 2500));
    try {
      const confirmed = await apiJson(`/payments/v1/universal/wallet-checkout/${pending.quote_id}/confirm`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (confirmed.status === "confirmed") {
        clearPendingCheckout(pending.quote_id);
        setInboxStatus(`Payment confirmed on devnet: ${shortAddress(pending.tx_signature)}. Delivery is now processing.`, "success");
        checkoutReview.hidden = true;
        await loadInbox(true);
        return true;
      }
    } catch (error) {
      if (error.status === 422) {
        clearPendingCheckout(pending.quote_id);
        throw new Error("The submitted transaction failed strict on-chain verification");
      }
      if (![409, 503].includes(error.status)) throw error;
    }
  }
  setInboxStatus(`Transaction ${shortAddress(pending.tx_signature)} is saved for automatic recovery. Reconnect this wallet later if confirmation is still pending.`, "success");
  return false;
}

async function resumePendingCheckout() {
  const pending = readPendingCheckout();
  if (!pending || pending.wallet !== sessionGet("iat_inbox_wallet")) return false;
  setInboxStatus(`Recovering submitted payment ${shortAddress(pending.tx_signature)}…`);
  try {
    await settlePendingCheckout(pending);
  } catch (error) {
    setInboxStatus(`Payment recovery paused: ${error.message}. Reconnect this wallet to retry.`, "error");
  }
  return true;
}

function safeDeliveryUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    const allowedHost = url.hostname === "iatprotocol.com" || url.hostname.endsWith(".pages.dev");
    return url.protocol === "https:" && allowedHost ? url.href : null;
  } catch (_) { return null; }
}

function renderDeliveries(items, append) {
  if (!append) {
    inboxItems.replaceChildren();
    displayedDeliveries = 0;
  }
  for (const item of items) {
    const article = document.createElement("article");
    article.className = "inbox-item";
    const summary = document.createElement("div");
    const quote = document.createElement("span");
    quote.textContent = item.quote_id;
    const state = document.createElement("small");
    state.textContent = `Status: ${item.final_receipt?.state || "available"}`;
    summary.append(quote, state);
    const deliveryUrl = safeDeliveryUrl(item.delivery_url);
    if (deliveryUrl) {
      const link = document.createElement("a");
      link.href = deliveryUrl;
      link.textContent = "Open verified receipt →";
      link.rel = "noopener";
      article.append(summary, link);
    } else {
      article.append(summary);
    }
    inboxItems.append(article);
    displayedDeliveries += 1;
  }
  inboxCount.textContent = `${displayedDeliveries} receipt${displayedDeliveries === 1 ? "" : "s"}`;
  inboxResults.hidden = false;
}

async function loadInbox(reset = false) {
  const token = sessionGet("iat_inbox_token");
  if (!token) return;
  if (reset) inboxCursor = null;
  setInboxStatus("Loading wallet deliveries…");
  try {
    const query = inboxCursor ? `?cursor=${encodeURIComponent(inboxCursor)}` : "";
    const result = await apiJson(`/payments/v1/universal/wallet-inbox${query}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    renderDeliveries(result.items || [], !reset);
    inboxCursor = result.next_cursor || null;
    inboxMore.hidden = !inboxCursor;
    setInboxStatus(result.count ? "Authenticated. Your receipts are ready." : "Authenticated. No delivery receipt is attached to this wallet yet.", "success");
  } catch (error) {
    if (error.status === 401) {
      clearInboxSession();
      walletSessionPanel.hidden = true;
      walletConnectPanel.hidden = false;
      inboxResults.hidden = true;
      throw new Error("Your inbox session expired. Connect the wallet again.");
    }
    throw error;
  }
}

walletConnect.addEventListener("click", async () => {
  walletConnect.disabled = true;
  try {
    await authenticateSelectedWallet();
    trackFunnel("wallet-inbox-opened");
  } catch (error) {
    setInboxStatus(`Unable to open inbox: ${error.message}`, "error");
  } finally {
    walletConnect.disabled = !discoveredWallets.length;
  }
});

walletRefresh.addEventListener("click", () => {
  setInboxStatus("Searching for Phantom, Solflare and Backpack…");
  scanInjectedWallets();
  window.dispatchEvent(new CustomEvent("wallet-standard:app-ready", {
    detail: Object.freeze({ register: registerWallets }),
  }));
});

walletDisconnect.addEventListener("click", async () => {
  const token = sessionGet("iat_inbox_token");
  clearInboxSession();
  if (token) {
    try {
      await apiJson("/payments/v1/universal/wallet-auth/session", {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch (_) { /* local logout remains effective */ }
  }
  try { await activeWallet?.features?.["standard:disconnect"]?.disconnect(); } catch (_) { /* optional feature */ }
  activeWallet = null;
  activeAccount = null;
  walletSessionPanel.hidden = true;
  walletConnectPanel.hidden = false;
  walletCheckout.hidden = true;
  inboxResults.hidden = true;
  setInboxStatus("Disconnected. The local inbox session was removed.");
});

inboxMore.addEventListener("click", async () => {
  inboxMore.disabled = true;
  try { await loadInbox(false); }
  catch (error) { setInboxStatus(`Unable to load more receipts: ${error.message}`, "error"); }
  finally { inboxMore.disabled = false; }
});

checkoutPrepare.addEventListener("click", async () => {
  checkoutPrepare.disabled = true;
  checkoutReview.hidden = true;
  preparedCheckout = null;
  try { await prepareCheckout(); }
  catch (error) { setInboxStatus(`Unable to prepare payment: ${error.message}`, "error"); }
  finally { checkoutPrepare.disabled = false; }
});

checkoutSend.addEventListener("click", async () => {
  checkoutSend.disabled = true;
  try { await confirmCheckoutInWallet(); }
  catch (error) {
    const pending = readPendingCheckout();
    const prefix = pending ? "Payment sent; recovery pending" : "Payment not sent";
    setInboxStatus(`${prefix}: ${error.message}`, "error");
  }
  finally { checkoutSend.disabled = false; }
});

usagePrepare.addEventListener("click", async () => {
  usagePrepare.disabled = true;
  usageReview.hidden = true;
  try { await prepareUsageInitialization(); }
  catch (error) { setInboxStatus(`Unable to check buyer setup: ${error.message}`, "error"); }
  finally { usagePrepare.disabled = false; }
});

usageSend.addEventListener("click", async () => {
  usageSend.disabled = true;
  try { await sendUsageInitialization(); }
  catch (error) { setInboxStatus(`Initialization not sent: ${error.message}`, "error"); }
  finally { usageSend.disabled = false; }
});

installWalletStandardDiscovery();
if (sellerSessionHeaders && document.querySelector(".seller-console-card")) {
  refreshSellerConsole().catch(() => {});
}
const restoredToken = sessionGet("iat_inbox_token");
const restoredWallet = sessionGet("iat_inbox_wallet");
if (restoredToken && restoredWallet) {
  showAuthenticatedWallet(restoredWallet);
  loadInbox(true).catch((error) => setInboxStatus(error.message, "error"));
}
