import { html, useEffect } from "../runtime/vendor.js";

export function StatusToast({ toast }) {
  const t = toast.value;
  const show = !!t?.show;
  const level = t?.level || "info";
  const msg = t?.msg || "";

  useEffect(() => {
    if (!show) return;
    const id = setTimeout(() => {
      toast.value = { ...toast.value, show: false };
    }, t?.ms || 2200);
    return () => clearTimeout(id);
  }, [show, msg]);

  return html`
    <div class=${`statusToast ${show ? "show" : ""} ${level}`} aria-hidden=${show ? "false" : "true"}>
      ${msg}
    </div>
  `;
}

