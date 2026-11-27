// NEXUS AGENT OS — frontend status panel.
//
// Frontend architecture rule: always use relative /api/... and /ws/... URLs so
// the same code works behind the nginx proxy in Docker and against a local dev
// server. Never hard-code localhost or 127.0.0.1.

const statusEl = document.getElementById("backend-status");
const payloadEl = document.getElementById("backend-payload");

async function checkBackend() {
  try {
    const response = await fetch("/api/health", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    statusEl.dataset.state = "ok";
    statusEl.textContent = `Backend healthy — ${payload.service} ${payload.version}`;
    payloadEl.hidden = false;
    payloadEl.textContent = JSON.stringify(payload, null, 2);
  } catch (error) {
    statusEl.dataset.state = "error";
    statusEl.textContent = `Backend unreachable: ${error.message}`;
    payloadEl.hidden = true;
  }
}

checkBackend();
// Poll so the panel reflects the stack coming up / going down.
window.setInterval(checkBackend, 15000);
