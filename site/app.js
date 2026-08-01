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
