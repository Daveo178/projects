const { spawn } = require("child_process");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9233;
async function main() {
  const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--hide-scrollbars",
    "--window-size=1600,1400", `--remote-debugging-port=${PORT}`, "about:blank"], { stdio: "ignore" });
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
  await send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1400, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: "http://localhost:8765" });
  await new Promise((res) => setTimeout(res, 16000));
  const r = await send("Runtime.evaluate", {
    expression: `(() => {
      const svg = document.querySelector('svg.marks');
      const sb = svg.getBoundingClientRect();
      const paths = svg.querySelectorAll('path');
      let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
      paths.forEach(p => { const b = p.getBoundingClientRect(); if (b.width === 0 && b.height === 0) return; minX = Math.min(minX, b.x); minY = Math.min(minY, b.y); maxX = Math.max(maxX, b.x + b.width); maxY = Math.max(maxY, b.y + b.height); });
      const all = svg.querySelectorAll('*');
      let aMinX = 1e9, aMinY = 1e9, aMaxX = -1e9, aMaxY = -1e9;
      all.forEach(el => { const b = el.getBoundingClientRect(); if (b.width === 0 && b.height === 0) return; aMinX = Math.min(aMinX, b.x); aMinY = Math.min(aMinY, b.y); aMaxX = Math.max(aMaxX, b.x + b.width); aMaxY = Math.max(aMaxY, b.y + b.height); });
      return JSON.stringify({
        svg: { x: Math.round(sb.x), y: Math.round(sb.y), w: Math.round(sb.width), h: Math.round(sb.height) },
        pathCount: paths.length,
        marks: { x: Math.round(minX), y: Math.round(minY), w: Math.round(maxX - minX), h: Math.round(maxY - minY) },
        allContent: { x: Math.round(aMinX), y: Math.round(aMinY), w: Math.round(aMaxX - aMinX), h: Math.round(aMaxY - aMinY) },
        samplePath: paths[0] ? paths[0].getAttribute('d').slice(0, 120) : null
      });
    })()`
  });
  console.log(JSON.stringify(JSON.parse(r.result?.result?.value), null, 1));
  ws.close(); chrome.kill();
}
main().catch(e => { console.error("ERR", e.message); process.exit(1); });
