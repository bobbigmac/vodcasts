import { useEffect, useRef, useSignal } from "../runtime/vendor.js";

export function useLongPress({ ms = 500, enabled = true, onLongPress } = {}) {
  const pressing = useSignal(false);
  const progress = useSignal(0);

  const optsRef = useRef({ ms, enabled, onLongPress });
  optsRef.current = { ms, enabled, onLongPress };

  const timerRef = useRef(null);
  const rafRef = useRef(null);
  const startMsRef = useRef(0);
  const didLongPressRef = useRef(false);

  const clear = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  };

  const consumeClick = () => {
    const v = didLongPressRef.current;
    didLongPressRef.current = false;
    return v;
  };

  const tick = () => {
    if (!pressing.value) return;
    const { ms: thresholdMs } = optsRef.current;
    const elapsed = Math.max(0, performance.now() - startMsRef.current);
    const p = thresholdMs > 0 ? Math.min(1, elapsed / thresholdMs) : 1;
    progress.value = p;
    rafRef.current = requestAnimationFrame(tick);
  };

  const onPointerDown = (e) => {
    const opts = optsRef.current;
    if (!opts.enabled) return;
    if (e.button != null && e.button !== 0) return;
    didLongPressRef.current = false;
    pressing.value = true;
    progress.value = 0;
    startMsRef.current = performance.now();

    try {
      e.currentTarget?.setPointerCapture?.(e.pointerId);
    } catch {}

    clear();
    rafRef.current = requestAnimationFrame(tick);
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      if (!pressing.value) return;
      didLongPressRef.current = true;
      pressing.value = false;
      progress.value = 1;
      try {
        opts.onLongPress?.();
      } catch {}
      clear();
    }, Math.max(0, Number(opts.ms) || 0));
  };

  const end = () => {
    if (!pressing.value) return;
    pressing.value = false;
    progress.value = 0;
    clear();
  };

  const onPointerUp = () => end();
  const onPointerCancel = () => end();

  useEffect(() => () => clear(), []);

  return { pressing, progress, onPointerDown, onPointerUp, onPointerCancel, consumeClick };
}
