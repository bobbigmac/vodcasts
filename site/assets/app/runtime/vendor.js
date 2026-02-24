// IMPORTANT: These esm.sh URLs are pinned + aligned so Preact hooks and
// @preact/signals share the exact same Preact instance (avoids hooks '__H'
// undefined errors caused by duplicate module instances).
import { h, render } from "https://esm.sh/preact@10.19.6/es2022/preact.mjs";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "https://esm.sh/preact@10.19.6/es2022/hooks.mjs";
import * as Signals from "https://esm.sh/@preact/signals@1.2.3?target=es2022&deps=preact@10.19.6";
import htm from "https://esm.sh/htm@3.1.1?target=es2022";

export const html = htm.bind(h);

export { h, render, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState };
export const { signal, computed, effect, batch, untracked, Signal, useSignal, useComputed, useSignalEffect } = Signals;
