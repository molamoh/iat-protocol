const API_BASE = "https://iat-protocol-latest.onrender.com";
const token = new URLSearchParams(location.hash.slice(1)).get("receipt");
const loading = document.querySelector("#loading");
const receiptPanel = document.querySelector("#receipt");
const status = document.querySelector("#decision-status");
let receiptState = null;

async function sha256(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function displayTime(value) {
  return value ? new Date(value * 1000).toLocaleString() : "Not recorded";
}

function setFinalState(state) {
  receiptState = state;
  document.querySelector("#receipt-state").textContent = state;
  const final = state === "accepted" || state === "disputed";
  const reviewable = state === "dispatched" || state === "delivered";
  document.querySelector("#decision-area").hidden = final || !reviewable;
  if (final) {
    status.className = `decision-status ${state === "accepted" ? "success" : "error"}`;
    status.textContent = state === "accepted" ? "Delivery accepted." : "Issue recorded for review.";
  }
}

async function loadReceipt() {
  if (!token || !token.startsWith("cdr_") || token.length > 128) {
    loading.className = "notice error";
    loading.textContent = "This delivery link is invalid.";
    return;
  }
  try {
    const response = await fetch(`${API_BASE}/payments/v1/universal/delivery-receipts/${encodeURIComponent(token)}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Receipt unavailable");
    const receipt = result.final_receipt;
    const inboxResponse = await fetch(`${API_BASE}/payments/v1/universal/delivery-receipts/${encodeURIComponent(token)}/inbox`, {cache:"no-store"});
    const inbox = await inboxResponse.json();
    if (!inboxResponse.ok) throw new Error(inbox.detail || "Delivery payload unavailable");
    const actualDigest = await sha256(inbox.canonical_result);
    if (actualDigest !== inbox.payload_digest) throw new Error("Delivery integrity verification failed");
    document.querySelector("#quote-id").textContent = result.quote_id;
    document.querySelector("#receipt-channel").textContent = receipt.channel;
    document.querySelector("#payload-digest").textContent = receipt.payload_digest || "Not sealed";
    document.querySelector("#dispatched-at").textContent = displayTime(receipt.dispatched_at);
    document.querySelector("#dispatch-signer").textContent = receipt.dispatch_signer || "Not signed";
    document.querySelector("#provider-status").textContent = receipt.provider_status || "Awaiting provider event";
    document.querySelector("#delivery-result").textContent = JSON.stringify(inbox.result, null, 2);
    const integrity = document.querySelector("#integrity-status");
    integrity.textContent = "SHA-256 verified";
    integrity.className = "verified";
    setFinalState(receipt.state);
    loading.hidden = true;
    receiptPanel.hidden = false;
  } catch (error) {
    loading.className = "notice error";
    loading.textContent = `Unable to load this receipt: ${error.message}`;
  }
}

async function decide(payload) {
  status.className = "decision-status";
  status.textContent = "Recording your final decision…";
  document.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  try {
    const response = await fetch(`${API_BASE}/payments/v1/universal/delivery-receipts/${encodeURIComponent(token)}/decision`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Decision rejected");
    setFinalState(result.final_receipt.state);
  } catch (error) {
    status.className = "decision-status error";
    status.textContent = `Unable to record the decision: ${error.message}`;
  } finally {
    document.querySelectorAll("button").forEach((button) => { button.disabled = false; });
  }
}

document.querySelector("#accept").addEventListener("click", () => decide({decision:"accepted",message:""}));
document.querySelector("#report").addEventListener("click", () => { document.querySelector("#dispute-form").hidden = false; });
document.querySelector("#cancel-dispute").addEventListener("click", () => { document.querySelector("#dispute-form").hidden = true; });
document.querySelector("#dispute-form").addEventListener("submit", (event) => {event.preventDefault();if(!event.target.reportValidity())return;const data=new FormData(event.target);decide({decision:"disputed",dispute_code:data.get("dispute_code"),message:data.get("message")});});

loadReceipt();
