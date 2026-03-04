import { useRef, useSignal, useSignalEffect } from "../../runtime/vendor.js";

export function usePanelTakeover({ defaultIdleMs = 5000 } = {}) {
  const active = useSignal(null);
  const idleTimerRef = useRef(null);

  const clearIdleTimer = () => {
    if (idleTimerRef.current) {
      clearTimeout(idleTimerRef.current);
      idleTimerRef.current = null;
    }
  };

  const close = () => {
    clearIdleTimer();
    active.value = null;
  };

  const bump = () => {
    if (!active.value) return;
    clearIdleTimer();
    const ms = Number(active.value.idleMs) > 0 ? Number(active.value.idleMs) : defaultIdleMs;
    idleTimerRef.current = setTimeout(() => close(), ms);
  };

  const open = (next) => {
    if (!next || !next.id) return;
    active.value = next;
    bump();
  };

  useSignalEffect(() => {
    if (!active.value) {
      clearIdleTimer();
      return;
    }
    bump();
    return () => clearIdleTimer();
  });

  return { active, open, close, bump };
}

