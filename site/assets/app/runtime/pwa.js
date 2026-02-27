export function initPwa(env, log) {
  try {
    if (env?.isDev) return;
    if (!("serviceWorker" in navigator)) return;
    const basePath = String(env?.basePath || "/");
    const url = basePath + "sw.js";

    const register = () => {
      navigator.serviceWorker
        .register(url, { scope: basePath })
        .then((reg) => {
          try {
            reg?.update?.();
          } catch {}
          try {
            log?.info?.(`PWA: registered (${reg?.scope || basePath})`);
          } catch {}
        })
        .catch((err) => {
          try {
            log?.warn?.(`PWA: register failed (${String(err?.message || err)})`);
          } catch {}
        });
    };

    if (document.readyState === "complete") register();
    else window.addEventListener("load", register, { once: true });
  } catch {}
}

