const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9235;

async function measure(url) {
  const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--hide-scrollbars",
    "--window-size=1400,900", `--remote-debugging-port=${PORT}`, "about:blank"], { stdio: "ignore" });
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
  await send("Emulation.setDeviceMetricsOverride", { width: 1400, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url });
  await new Promise((res) => setTimeout(res, 8000));
  const r = await send("Runtime.evaluate", {
    expression: `(() => {
      const svg = document.querySelector('svg');
      if (!svg) return null;
      const sb = svg.getBoundingClientRect();
      const vb = (svg.getAttribute('viewBox') || '').split(' ').map(Number);
      let minY = 1e9, maxY = -1e9;
      document.querySelectorAll('svg path').forEach(p => { const b = p.getBoundingClientRect(); if (b.height > 0) { minY = Math.min(minY, b.y); maxY = Math.max(maxY, b.y + b.height); } });
      return JSON.stringify({ svgH: Math.round(sb.height), viewBox: vb, pathTop: Math.round(minY - sb.y), pathBottom: Math.round(maxY - sb.y), pathSpan: Math.round(maxY - minY) });
    })()`
  });
  const res = JSON.parse(r.result?.result?.value || "null");
  ws.close(); chrome.kill();
  return res;
}

(async () => {
  const dir = path.resolve("tmp_bare");
  for (const f of fs.readdirSync(dir).filter(f => f.endsWith(".html"))) {
    const url = "file:///" + path.join(dir, f).replace(/\\/g, "/");
    const m = await measure(url);
    console.log(`${f}: svgH=${m?.svgH} viewBox=${JSON.stringify(m?.viewBox)} paths y ${m?.pathTop}-${m?.pathBottom} (span ${m?.pathSpan})`);
  }
})();
