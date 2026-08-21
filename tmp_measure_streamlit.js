const { spawn } = require("child_process");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9236;
async function main() {
  const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--hide-scrollbars",
    "--window-size=1600,1600", `--remote-debugging-port=${PORT}`, "about:blank"], { stdio: "ignore" });
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
  await send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1600, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: "http://localhost:8765" });
  await new Promise((res) => setTimeout(res, 16000));
  const r = await send("Runtime.evaluate", {
    expression: `(() => {
      const out = [];
      let idx = 0;
      document.querySelectorAll('svg.marks').forEach(svg => {
        const sb = svg.getBoundingClientRect();
        let minY = 1e9, maxY = -1e9, minX = 1e9, maxX = -1e9;
        svg.querySelectorAll('path').forEach(p => { const b = p.getBoundingClientRect(); if (b.height > 0 || b.width > 0) { minY = Math.min(minY, b.y); maxY = Math.max(maxY, b.y + b.height); minX = Math.min(minX, b.x); maxX = Math.max(maxX, b.x + b.width); } });
        const ticks = [];
        svg.querySelectorAll('text').forEach(t => { const s = t.textContent; if (s && /^[\\d,]+$/.test(s.trim())) ticks.push(s.trim()); });
        out.push({ idx: idx++, svgY: Math.round(sb.y), svgH: Math.round(sb.height),
                   pathY: Math.round(minY - sb.y), pathSpan: Math.round(maxY - minY),
                   yticks: [...new Set(ticks)].slice(-10) });
      });
      return JSON.stringify(out);
    })()`
  });
  const d = JSON.parse(r.result?.result?.value || "[]");
  d.forEach(c => console.log(`chart ${c.idx}: svg_y=${c.svgY} svg_h=${c.svgH} paths_y=${c.pathY} span=${c.pathSpan} yticks=${JSON.stringify(c.yticks)}`));
  ws.close(); chrome.kill();
}
main().catch(e => { console.error("ERR", e.message); process.exit(1); });
