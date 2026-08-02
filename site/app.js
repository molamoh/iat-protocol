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
const discoveredWallets = [];
const registeredLegacyProviders = new WeakSet();
let activeWallet = null;
let activeAccount = null;
let inboxCursor = null;
let displayedDeliveries = 0;

function sessionGet(key) {
  try { return sessionStorage.getItem(key); } catch (_) { return null; }
}

function sessionSet(key, value) {
  try { sessionStorage.setItem(key, value); } catch (_) { /* memory-only fallback */ }
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
  await loadInbox(true);
}

function showAuthenticatedWallet(address) {
  walletConnectPanel.hidden = true;
  walletSessionPanel.hidden = false;
  walletAddress.textContent = shortAddress(address);
  walletAddress.title = address;
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
  inboxResults.hidden = true;
  setInboxStatus("Disconnected. The local inbox session was removed.");
});

inboxMore.addEventListener("click", async () => {
  inboxMore.disabled = true;
  try { await loadInbox(false); }
  catch (error) { setInboxStatus(`Unable to load more receipts: ${error.message}`, "error"); }
  finally { inboxMore.disabled = false; }
});

installWalletStandardDiscovery();
const restoredToken = sessionGet("iat_inbox_token");
const restoredWallet = sessionGet("iat_inbox_wallet");
if (restoredToken && restoredWallet) {
  showAuthenticatedWallet(restoredWallet);
  loadInbox(true).catch((error) => setInboxStatus(error.message, "error"));
}
