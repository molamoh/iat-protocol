const API = "https://iat-protocol-latest.onrender.com";
let session = null;
const $ = (id) => document.getElementById(id);
const setStatus = (message, type = "") => {
  $("status").className = `order-status ${type}`;
  $("status").textContent = message;
};
async function request(path, body) {
  const response = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || result.message || "request_rejected");
  return result;
}
fetch(`${API}/health?v=order-board`).then((response) => response.json()).then((result) => {
  $("protocol-card").className = "order-card ok";
  $("protocol-card").querySelector("strong").textContent = `Opérationnel · ${result.build_version || "version active"}`;
}).catch(() => {
  $("protocol-card").className = "order-card wait";
  $("protocol-card").querySelector("strong").textContent = "Vérification indisponible";
});
$("preview").addEventListener("click", async () => {
  const wallet = $("wallet").value.trim();
  const prompt = $("prompt").value.trim();
  if (!wallet || !prompt) return setStatus("Renseigne le wallet public et la demande.", "error");
  $("preview").disabled = true;
  $("confirm").disabled = true;
  setStatus("Prévisualisation gouvernée en cours…");
  try {
    const result = await request("/buyer/preview", { buyer_wallet: wallet, prompt, max_price: Number($("max").value || 0) });
    session = result.session_id;
    $("result").hidden = false;
    $("result").textContent = JSON.stringify(result, null, 2);
    $("confirm").disabled = !session;
    setStatus("Offre prête. Vérifie le détail puis confirme. Aucun paiement n’a eu lieu.", "success");
  } catch (error) { setStatus(`Prévisualisation refusée : ${error.message}`, "error"); }
  finally { $("preview").disabled = false; }
});
$("confirm").addEventListener("click", async () => {
  if (!session) return;
  $("confirm").disabled = true;
  setStatus("Création de l’ordre gouverné…");
  try {
    const result = await request("/buyer/confirm", { buyer_wallet: $("wallet").value.trim(), session_id: session, max_price: Number($("max").value || 0) });
    $("result").hidden = false;
    $("result").textContent = JSON.stringify(result, null, 2);
    if (!result.order_id) throw new Error(result.message || "order_id_missing");
    $("order-id").textContent = result.order_id;
    $("next").hidden = false;
    setStatus("Commande créée. Aucun fonds n’a été déplacé.", "success");
  } catch (error) { setStatus(`Création refusée : ${error.message}`, "error"); $("confirm").disabled = false; }
});
$("copy").addEventListener("click", async () => { await navigator.clipboard.writeText($("order-id").textContent); $("copy").textContent = "Copié"; });
