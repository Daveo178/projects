const { spawn } = require("child_process");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9231;
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
      const out = [];
      let i = 0;
      document.querySelectorAll('svg.marks').forEach(svg => {
        const firstG = svg.querySelector('g');
        const sb = svg.getBoundingClientRect();
        const gb = firstG ? firstG.getBoundingClientRect() : null;
        const ticks = [];
        svg.querySelectorAll('g').forEach(g => {
          const role = g.getAttribute('role') || '';
          if (role.includes('axis')) {
            g.querySelectorAll(':scope > g').forEach(t => {
              const lbl = t.textContent;
              if (lbl && !lbl.includes('Age')) ticks.push(lbl.slice(0, 10));
            });
          }
        });
        out.push({ n: i, svgH: Math.round(sb.height), gY: gb ? Math.round(gb.y) : null,
                   gH: gb ? Math.round(gb.height) : null, ticks: [...new Set(ticks)].slice(0, 12) });
        i++;
      });
      return JSON.stringify(out);
    })()`
  });
  const d = JSON.parse(r.result?.result?.value || "[]");
  d.forEach(c => console.log(`chart ${c.n}: svg_h=${c.svgH} group_y=${c.gY} group_h=${c.gH} ticks=${JSON.stringify(c.ticks)}`));
  ws.close(); chrome.kill();
}
main().catch(e => { console.error("ERR", e.message); process.exit(1); });
