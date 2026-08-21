const { spawn } = require("child_process");
const fs = require("fs");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9238;
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
  // Measure chart index 2 (fit-x) path span
  const r = await send("Runtime.evaluate", {
    expression: `(() => {
      const svgs = document.querySelectorAll('svg.marks');
      const svg = svgs[2];
      if (!svg) return null;
      const sb = svg.getBoundingClientRect();
      let minY = 1e9, maxY = -1e9;
      svg.querySelectorAll('path').forEach(p => { const b = p.getBoundingClientRect(); if (b.height > 0) { minY = Math.min(minY, b.y); maxY = Math.max(maxY, b.y + b.height); } });
      return JSON.stringify({ svg: { x: Math.round(sb.x), y: Math.round(sb.y), w: Math.round(sb.width), h: Math.round(sb.height) }, pathTop: Math.round(minY - sb.y), pathBottom: Math.round(maxY - sb.y), pathSpan: Math.round(maxY - minY) });
    })()`
  });
  console.log("fit-x chart:", JSON.stringify(JSON.parse(r.result?.result?.value)));
  const shot = await send("Page.captureScreenshot", { format: "png" });
  fs.writeFileSync("tmp_fitx.png", Buffer.from(shot.result.data, "base64"));
  console.log("screenshot saved", Buffer.from(shot.result.data, "base64").length);
  ws.close(); chrome.kill();
}
main().catch(e => { console.error("ERR", e.message); process.exit(1); });
