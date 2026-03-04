import { html, useEffect, useMemo, useRef, useSignal } from "../runtime/vendor.js";

function fmtTime(s) {
  s = Math.max(0, Math.floor(s || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

function stableContentId(source, episode) {
  const sid = source?.id || "unknown";
  const eid = episode?.id || "unknown";
  return `vodcasts:${sid}:${eid}`;
}

function ensureHcaptchaLoaded() {
  return new Promise((resolve) => {
    if (window.hcaptcha) return resolve();
    if (window.__vodcastsHCaptchaLoading) {
      window.__vodcastsHCaptchaLoading.push(resolve);
      return;
    }
    window.__vodcastsHCaptchaLoading = [resolve];
    window.onHCaptchaLoad = function () {
      const list = window.__vodcastsHCaptchaLoading || [];
      window.__vodcastsHCaptchaLoading = null;
      list.forEach((r) => r());
    };
    const s = document.createElement("script");
    s.src = "https://js.hcaptcha.com/1/api.js?onload=onHCaptchaLoad&render=explicit";
    s.async = true;
    s.defer = true;
    document.head.appendChild(s);
  });
}

export function TimedComments({ env, player, isActive }) {
  const cfg = env?.site?.comments || {};

  const status = useSignal("—");
  const rows = useSignal([]);
  const anonReady = useSignal(false);
  const posting = useSignal(false);
  const name = useSignal("");
  const body = useSignal("");

  const showCaptcha = useSignal(false);
  const captchaBtnDisabled = useSignal(false);

  const sbRef = useRef(null);
  const contentIdRef = useRef(null);
  const channelRef = useRef(null);
  const captchaWidgetIdRef = useRef(null);
  const captchaTokenRef = useRef(null);
  const captchaContainerRef = useRef(null);

  const cur = player.current.value;
  const contentId = useMemo(() => stableContentId(cur.source, cur.episode), [cur.source?.id, cur.episode?.id]);

  const timeLabel = fmtTime(player.playback.value.time || 0);

  async function ensureClient() {
    if (sbRef.current) return sbRef.current;
    if (!cfg?.supabaseUrl || !cfg?.supabaseAnonKey) return null;
    const mod = await import("https://esm.sh/@supabase/supabase-js@2.49.1");
    sbRef.current = mod.createClient(cfg.supabaseUrl, cfg.supabaseAnonKey);
    return sbRef.current;
  }

  async function load() {
    const sb = sbRef.current;
    const cid = contentIdRef.current;
    if (!sb || !cid) return;
    const { data, error } = await sb
      .from("timed_comments")
      .select("id,t_seconds,name,body,created_at")
      .eq("content_id", cid)
      .order("t_seconds", { ascending: true })
      .order("created_at", { ascending: true });
    if (error) throw error;
    rows.value = data ?? [];
  }

  async function initCaptchaIfNeeded() {
    if (!cfg?.hcaptchaSitekey) return null;
    if (captchaWidgetIdRef.current) return captchaWidgetIdRef.current;
    await ensureHcaptchaLoaded();
    showCaptcha.value = true;
    await new Promise((r) => setTimeout(r, 0));
    const host = captchaContainerRef.current;
    if (!host) return null;
    host.style.display = "none";
    captchaWidgetIdRef.current = hcaptcha.render(host, {
      sitekey: cfg.hcaptchaSitekey,
      size: "invisible",
      callback: (token) => {
        captchaTokenRef.current = token;
      },
      "error-callback": () => {
        captchaTokenRef.current = null;
      },
    });
    return captchaWidgetIdRef.current;
  }

  async function ensureAnon() {
    const sb = await ensureClient();
    if (!sb) return;
    const { data: sess } = await sb.auth.getSession();
    if (sess?.session) return;

    if (cfg?.hcaptchaSitekey) {
      await initCaptchaIfNeeded();
      status.value = "click Continue…";
      captchaBtnDisabled.value = false;
      showCaptcha.value = true;

      return; // wait for user to click Continue (and execute captcha)
    }

    const { error } = await sb.auth.signInAnonymously();
    if (error) throw error;
  }

  async function signInWithCaptchaIfReady() {
    const sb = await ensureClient();
    if (!sb) return;
    const { data: sess } = await sb.auth.getSession();
    if (sess?.session) return;
    const token = captchaTokenRef.current;
    if (!token) throw new Error("Captcha required");
    const { error } = await sb.auth.signInAnonymously({ options: { captchaToken: token } });
    if (error) throw error;
  }

  useEffect(() => {
    if (!isActive) return;

    const hasCfg = !!(cfg?.supabaseUrl && cfg?.supabaseAnonKey);
    if (!hasCfg) {
      status.value = "comments disabled";
      rows.value = [];
      anonReady.value = false;
      showCaptcha.value = false;
      return;
    }

    if (!cur?.source?.id || !cur?.episode?.id) {
      status.value = "select an episode";
      rows.value = [];
      anonReady.value = false;
      showCaptcha.value = false;
      return;
    }

    let cancelled = false;
    contentIdRef.current = contentId;
    anonReady.value = false;
    rows.value = [];

    (async () => {
      try {
        status.value = "signing in…";
        await ensureAnon();
        if (cfg?.hcaptchaSitekey) {
          // waiting for user gesture; keep UI in "Continue" mode
          return;
        }
        if (cancelled) return;
        anonReady.value = true;
        status.value = "loading…";
        await load();
        if (cancelled) return;
        status.value = contentId;

        channelRef.current?.unsubscribe?.();
        channelRef.current = sbRef.current
          .channel(`timed_comments:${contentId}`)
          .on(
            "postgres_changes",
            { event: "INSERT", schema: "public", table: "timed_comments", filter: `content_id=eq.${contentId}` },
            () => load()
          )
          .subscribe();
      } catch (err) {
        console.error(err);
        status.value = "error (check console)";
      }
    })();

    return () => {
      cancelled = true;
      channelRef.current?.unsubscribe?.();
      channelRef.current = null;
    };
  }, [isActive, contentId, cfg?.supabaseUrl, cfg?.supabaseAnonKey, cfg?.hcaptchaSitekey, cur?.source?.id, cur?.episode?.id]);

  async function onContinue() {
    captchaBtnDisabled.value = true;
    status.value = "verifying…";
    try {
      await initCaptchaIfNeeded();
      captchaTokenRef.current = null;
      hcaptcha.execute(captchaWidgetIdRef.current);

      // Wait a short while for callback to fire.
      const t0 = Date.now();
      while (!captchaTokenRef.current && Date.now() - t0 < 15000) {
        await new Promise((r) => setTimeout(r, 50));
      }

      await signInWithCaptchaIfReady();
      anonReady.value = true;
      showCaptcha.value = false;
      status.value = "loading…";
      await load();
      status.value = contentIdRef.current || "—";

      channelRef.current?.unsubscribe?.();
      channelRef.current = sbRef.current
        .channel(`timed_comments:${contentIdRef.current}`)
        .on(
          "postgres_changes",
          { event: "INSERT", schema: "public", table: "timed_comments", filter: `content_id=eq.${contentIdRef.current}` },
          () => load()
        )
        .subscribe();
    } catch (err) {
      console.error(err);
      status.value = "error (check console)";
      captchaBtnDisabled.value = false;
    }
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (!anonReady.value || !sbRef.current || !contentIdRef.current) return;
    if (!body.value.trim()) return;
    posting.value = true;
    try {
      const { data: userData, error: userErr } = await sbRef.current.auth.getUser();
      if (userErr) throw userErr;
      const payload = {
        content_id: contentIdRef.current,
        t_seconds: Math.max(0, Math.floor(player.playback.value.time || 0)),
        name: name.value.trim() || null,
        body: body.value.trim(),
        user_id: userData.user.id,
      };
      const { error } = await sbRef.current.from("timed_comments").insert(payload);
      if (error) throw error;
      body.value = "";
      await load();
    } finally {
      posting.value = false;
    }
  }

  const formHidden = !anonReady.value;
  const postDisabled = posting.value || !anonReady.value || !body.value.trim();

  return html`
    <div class="commentsTop">
      <div id="commentsStatus" class="commentsStatus">${status.value}</div>
    </div>

    <div id="commentsCaptchaWrap" class="commentsCaptchaWrap" hidden=${!showCaptcha.value}>
      <button type="button" id="captchaBtn" class="guideBtn" disabled=${captchaBtnDisabled.value} onClick=${onContinue}>
        Continue
      </button>
      <div ref=${captchaContainerRef} id="hcaptcha-container"></div>
    </div>

    <form id="commentsForm" class="commentsForm" autocomplete="off" hidden=${formHidden} onSubmit=${onSubmit}>
      <input
        id="commentName"
        name="commentName"
        placeholder="display name (optional)"
        maxlength="64"
        value=${name.value}
        onInput=${(e) => (name.value = e.target.value)}
      />
      <textarea
        id="commentBody"
        placeholder="say something…"
        maxlength="4000"
        required
        value=${body.value}
        onInput=${(e) => (body.value = e.target.value)}
      ></textarea>
      <button id="commentSubmit" type="submit" class="guideBtn" disabled=${postDisabled}>
        Post @ <span id="commentTime">${timeLabel}</span>
      </button>
    </form>

    <div id="commentsList" class="commentsList">
      ${rows.value.map(
        (r) => html`
          <div class="commentRow">
            <div class="commentMeta">
              <span
                class="commentTime"
                title="jump to time"
                onClick=${() => {
                  const t = Number(r.t_seconds) || 0;
                  player.seekToTime(t);
                  player.play({ userGesture: true });
                }}
              >
                ${fmtTime(r.t_seconds)}
              </span>
              <span>${r.name ? r.name : "anon"}</span>
              <span>${new Date(r.created_at).toLocaleString()}</span>
            </div>
            <div class="commentBody">${r.body}</div>
          </div>
        `
      )}
    </div>
  `;
}
