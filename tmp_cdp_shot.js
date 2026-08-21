const { spawn } = require("child_process");
const fs = require("fs");

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9224;

async function main() {
  const chrome = spawn(CHROME, [
    "--headless=new", "--disable-gpu", "--hide-scrollbars",
    "--window-size=1600,1100",
    `--remote-debugging-port=${PORT}`,
    "about:blank",
  ], { stdio: "ignore" });

  let ok = false;
  for (let i = 0; i < 40; i++) {
    try { const r = await fetch(`http://localhost:${PORT}/json/version`); if (r.ok) { ok = true; break; } } catch {}
    await new Promise((res) => setTimeout(res, 250));
  }
  if (!ok) { console.log("FAIL: no debugger"); chrome.kill(); process.exit(1); }

  const tab = await (await fetch(`http://localhost:${PORT}/json/new?about:blank`, { method: "PUT" })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let msgId = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  };
  function send(method, params = {}) {
    return new Promise((res) => {
      const id = ++msgId;
      pending.set(id, res);
      ws.send(JSON.stringify({ id, method, params }));
    });
  }

  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1100, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: "http://localhost:8765" });
  await new Promise((res) => setTimeout(res, 14000));

  const shot = await send("Page.captureScreenshot", { format: "png" });
  const buf = Buffer.from(shot.result.data, "base64");
  fs.writeFileSync("tmp_plan_chart.png", buf);
  console.log("screenshot bytes:", buf.length);

  const ticks = await send("Runtime.evaluate", {
    expression: `(() => {
      const texts = [];
      document.querySelectorAll('svg text').forEach(t => texts.push(t.textContent));
      return texts.slice(0, 40).join(' | ');
    })()`
  });
  console.log("svg texts:", (ticks.result?.result?.value || "").slice(0, 400));
  ws.close();
  chrome.kill();
}

main().catch((e) => { console.error("ERR", e.message); process.exit(1); });
