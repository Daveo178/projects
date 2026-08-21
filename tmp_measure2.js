const { spawn } = require("child_process");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9237;
async function main() {
  const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--hide-scrollbars",
    "--window-size=1600,2200", `--remote-debugging-port=${PORT}`, "about:blank"], { stdio: "ignore" });
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
  await send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 2200, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: "http://localhost:8765" });
  await new Promise((res) => setTimeout(res, 16000));
  const r = await send("Runtime.evaluate", {
    expression: `(() => {
      const out = [];
      let idx = 0;
      document.querySelectorAll('svg.marks').forEach(svg => {
        const b = svg.getBoundingClientRect();
        const vb = svg.getAttribute('viewBox') || '';
        const ticks = [];
        svg.querySelectorAll('text').forEach(t => { const s = t.textContent.trim(); if (s && /^[\\d,]+$/.test(s)) ticks.push(s); });
        out.push({ idx: idx++, w: Math.round(b.width), h: Math.round(b.height), viewBox: vb, yticks: [...new Set(ticks)] });
      });
      return JSON.stringify(out);
    })()`
  });
  const d = JSON.parse(r.result?.result?.value || "[]");
  d.forEach(c => console.log(`chart ${c.idx}: ${c.w}x${c.h} viewBox=${c.viewBox} yticks=${JSON.stringify(c.yticks)}`));
  ws.close(); chrome.kill();
}
main().catch(e => { console.error("ERR", e.message); process.exit(1); });
