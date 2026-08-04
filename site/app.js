const API_BASE = "https://iat-protocol-latest.onrender.com";
const tracked = new Set();

function trackFunnel(eventName) {
  if (tracked.has(eventName)) return;
  tracked.add(eventName);
  const safeName = String(eventName).replace(/[^a-z0-9-]/g, "");
  history.pushState({ iatFunnel: safeName }, "", `/funnel/${safeName}`);
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

const form = document.querySelector("#pilot-form");
const status = document.querySelector("#form-status");

const sandboxService = document.querySelector("#sandbox-service");
const sandboxGoal = document.querySelector("#sandbox-goal");
const sandboxBudget = document.querySelector("#sandbox-budget");
const sandboxStrategy = document.querySelector("#sandbox-strategy");
const sandboxDiscover = document.querySelector("#sandbox-discover");
const sandboxRun = document.querySelector("#sandbox-run");
const sandboxStatus = document.querySelector("#sandbox-status");
const sandboxResult = document.querySelector("#sandbox-result");

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

const walletSelector = document.querySelector("#wallet-selector");
const walletConnect = document.querySelector("#wallet-connect");
const walletRefresh = document.querySelector("#wallet-refresh");
const walletDisconnect = document.querySelector("#wallet-disconnect");
const walletConnectPanel = document.querySelector("#wallet-connect-panel");
const walletSessionPanel = document.querySelector("#wallet-session-panel");
const walletAddress = document.querySelector("#wallet-address");
const inboxStatus = document.querySelector("#inbox-status");
const inboxResults = document.querySelector("#inbox-results");
const inboxItems = document.querySelector("#inbox-items");
const inboxCount = document.querySelector("#inbox-count");
const inboxMore = document.querySelector("#inbox-more");
const walletCheckout = document.querySelector("#wallet-checkout");
const checkoutOrderId = document.querySelector("#checkout-order-id");
const checkoutPrepare = document.querySelector("#checkout-prepare");
const checkoutReview = document.querySelector("#checkout-review");
const checkoutSend = document.querySelector("#checkout-send");
const usagePrepare = document.querySelector("#usage-prepare");
const usageReview = document.querySelector("#usage-review");
const usageSend = document.querySelector("#usage-send");
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
const restoredToken = sessionGet("iat_inbox_token");
const restoredWallet = sessionGet("iat_inbox_wallet");
if (restoredToken && restoredWallet) {
  showAuthenticatedWallet(restoredWallet);
  loadInbox(true).catch((error) => setInboxStatus(error.message, "error"));
}
