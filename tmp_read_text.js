const { spawn } = require("child_process");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9226;
async function main() {
  const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--hide-scrollbars",
    "--window-size=1600,1100", `--remote-debugging-port=${PORT}`, "about:blank"], { stdio: "ignore" });
  let ok = false;
  for (let i = 0; i < 40; i++) {
    try { const r = await fetch(`http://localhost:${PORT}/json/version`); if (r.ok) { ok = true; break; } } catch {}
    await new Promise((res) => setTimeout(res, 250));
  }
  if (!ok) { console.log("FAIL: no debugger"); chrome.kill(); process.exit(1); }
  const tab = await (await fetch(`http://localhost:${PORT}/json/new?about:blank`, { method: "PUT" })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let msgId = 0; const pending = new Map();
  ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
  const send = (method, params = {}) => new Promise((res) => { const id = ++msgId; pending.set(id, res); ws.send(JSON.stringify({ id, method, params })); });
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1100, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: "http://localhost:8765" });
  await new Promise((res) => setTimeout(res, 14000));
  const body = await send("Runtime.evaluate", { expression: "document.body.innerText" });
  console.log("BODY TEXT:\n" + (body.result?.result?.value || "").slice(0, 800));
  const svg = await send("Runtime.evaluate", {
    expression: `(() => { const t=[]; document.querySelectorAll('svg text').forEach(x=>t.push(x.textContent)); return t.join(' | '); })()`
  });
  console.log("\nSVG TEXTS:", (svg.result?.result?.value || ""));
  ws.close(); chrome.kill();
}
main().catch(e => { console.error("ERR", e.message); process.exit(1); });
