import { html } from "../runtime/vendor.js";

export function MoonIcon({ size = 16, strokeWidth = 2, className = "" } = {}) {
  const s = Number(size) > 0 ? Number(size) : 16;
  const sw = Number(strokeWidth) > 0 ? Number(strokeWidth) : 2;
  return html`
    <svg
      class=${className}
      width=${s}
      height=${s}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width=${sw}
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M12 3a6 6 0 0 0 9 9a9 9 0 1 1-9-9Z"></path>
    </svg>
  `;
}

export function PlayIcon({ size = 16, className = "" } = {}) {
  const s = Number(size) > 0 ? Number(size) : 16;
  return html`
    <svg
      class=${className}
      width=${s}
      height=${s}
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M8 5v14l12-7-12-7Z"></path>
    </svg>
  `;
}

export function PauseIcon({ size = 16, className = "" } = {}) {
  const s = Number(size) > 0 ? Number(size) : 16;
  return html`
    <svg
      class=${className}
      width=${s}
      height=${s}
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M7 5h4v14H7V5Zm6 0h4v14h-4V5Z"></path>
    </svg>
  `;
}

export function FullscreenIcon({ size = 18, strokeWidth = 2, className = "" } = {}) {
  const s = Number(size) > 0 ? Number(size) : 18;
  const sw = Number(strokeWidth) > 0 ? Number(strokeWidth) : 2;
  return html`
    <svg
      class=${className}
      width=${s}
      height=${s}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width=${sw}
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M9 3H3v6"></path>
      <path d="M15 3h6v6"></path>
      <path d="M3 15v6h6"></path>
      <path d="M21 15v6h-6"></path>
    </svg>
  `;
}

export function ExitFullscreenIcon({ size = 18, strokeWidth = 2, className = "" } = {}) {
  const s = Number(size) > 0 ? Number(size) : 18;
  const sw = Number(strokeWidth) > 0 ? Number(strokeWidth) : 2;
  return html`
    <svg
      class=${className}
      width=${s}
      height=${s}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width=${sw}
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M3 9h6V3"></path>
      <path d="M21 9h-6V3"></path>
      <path d="M3 15h6v6"></path>
      <path d="M21 15h-6v6"></path>
    </svg>
  `;
}

export function MuteIcon({ size = 18, strokeWidth = 2, className = "" } = {}) {
  const s = Number(size) > 0 ? Number(size) : 18;
  const sw = Number(strokeWidth) > 0 ? Number(strokeWidth) : 2;
  return html`
    <svg
      class=${className}
      width=${s}
      height=${s}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width=${sw}
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M11 5 6 9H2v6h4l5 4V5Z"></path>
      <path d="M23 9 17 15"></path>
      <path d="M17 9 23 15"></path>
    </svg>
  `;
}

export function ShareIcon({ size = 18, strokeWidth = 2, className = "" } = {}) {
  const s = Number(size) > 0 ? Number(size) : 18;
  const sw = Number(strokeWidth) > 0 ? Number(strokeWidth) : 2;
  return html`
    <svg
      class=${className}
      width=${s}
      height=${s}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width=${sw}
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M12 3v10"></path>
      <path d="M8 7l4-4 4 4"></path>
      <path d="M6 11v8a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2v-8"></path>
    </svg>
  `;
}

export function ShuffleIcon({ size = 18, strokeWidth = 2, className = "" } = {}) {
  const s = Number(size) > 0 ? Number(size) : 18;
  const sw = Number(strokeWidth) > 0 ? Number(strokeWidth) : 2;
  return html`
    <svg
      class=${className}
      width=${s}
      height=${s}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width=${sw}
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <polyline points="16 3 21 3 21 8"></polyline>
      <polyline points="16 21 21 21 21 16"></polyline>
      <path d="M4 7h5c2.8 0 4.6 2.4 6.2 4.8 1.5 2.2 3 4.2 5.8 4.2h0"></path>
      <path d="M4 17h5c1.6 0 2.8-0.9 3.8-2"></path>
      <path d="M16 6h2c1.5 0 2.2 0.5 3 1.4"></path>
    </svg>
  `;
}
