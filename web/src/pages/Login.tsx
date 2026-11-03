import { useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type Config, type LoginState } from "../api";
import { ChatGPTDeviceCode } from "../components/ChatGPT";
import { Button, Input, Spinner } from "../ui";

declare global {
  interface Window {
    Clerk?: any;
    __internal_ClerkUICtor?: any;
  }
}

function loadScript(src: string, attrs: Record<string, string> = {}) {
  return new Promise<void>((ok, fail) => {
    const s = document.createElement("script");
    s.src = src;
    s.async = true;
    s.crossOrigin = "anonymous";
    Object.entries(attrs).forEach(([k, v]) => s.setAttribute(k, v));
    s.onload = () => ok();
    s.onerror = () => fail(new Error("Could not load Google sign-in"));
    document.head.appendChild(s);
  });
}

async function loadClerk(cfg: NonNullable<Config["clerk"]>) {
  if (!window.Clerk) {
    await loadScript(`https://${cfg.frontend_api}/npm/@clerk/ui@1/dist/ui.browser.js`);
    await loadScript(`https://${cfg.frontend_api}/npm/@clerk/clerk-js@6/dist/clerk.browser.js`, { "data-clerk-publishable-key": cfg.publishable_key });
  }
  const clerk = window.Clerk;
  await clerk.load({ telemetry: false, ui: { ClerkUI: window.__internal_ClerkUICtor } });
  return clerk;
}

function ClerkSignIn({ cfg, onDone }: { cfg: NonNullable<Config["clerk"]>; onDone: () => void }) {
  const mount = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "form" | "exchanging" | "error">("loading");
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    const exchange = async (session: any) => {
      setState("exchanging");
      try {
        await api("/auth/clerk", { body: { token: await session.getToken() } });
        onDone();
      } catch (e: any) {
        setError(e.message);
        setState("error");
      }
    };
    (async () => {
      try {
        const clerk = await loadClerk(cfg);
        if (!alive) return;
        if (clerk.session) return exchange(clerk.session);
        setState("form");
        clerk.mountSignIn(mount.current, { forceRedirectUrl: location.href, signUpForceRedirectUrl: location.href });
        clerk.addListener(({ session }: any) => session && exchange(session));
      } catch (e: any) {
        setError(e.message);
        setState("error");
      }
    })();
    return () => {
      alive = false;
    };
  }, []);
  return (
    <div>
      {(state === "loading" || state === "exchanging") && (
        <div className="flex justify-center py-6">
          <Spinner />
        </div>
      )}
      <div ref={mount} className="flex justify-center" />
      {state === "error" && (
        <div className="mt-3 rounded-xl bg-[#fdecea] p-3 text-sm text-danger">
          {error}
          <button
            className="ml-2 underline"
            onClick={async () => {
              try {
                await window.Clerk?.signOut();
              } catch {
                /* ignore */
              }
              location.reload();
            }}
          >
            Use another account
          </button>
        </div>
      )}
    </div>
  );
}

function PasswordSignIn({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
          await api("/auth/password", { body: { email, password } });
          onDone();
        } catch (err: any) {
          setError(err.message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <Input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
      <Input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
      {error && <div className="text-sm text-danger">{error}</div>}
      <Button variant="primary" className="w-full" loading={busy}>
        Sign in
      </Button>
    </form>
  );
}

export default function Login({ cfg }: { cfg: Config }) {
  const qc = useQueryClient();
  const hasClerk = cfg.auth_modes.includes("clerk") && !!cfg.clerk;
  // Coming back from Google: reopen Clerk so it can finish the sign-in.
  const [mode, setMode] = useState<"choose" | "google" | "chatgpt">(() =>
    hasClerk && location.hash.startsWith("#/sso-callback") ? "google" : "choose",
  );
  const done = () => {
    qc.invalidateQueries();
    location.reload();
  };
  const hasChatGPT = cfg.auth_modes.includes("chatgpt");
  const hasPassword = cfg.auth_modes.includes("password");
  return (
    <div className="relative grid min-h-screen place-items-center overflow-hidden px-4 py-10">
      <div className="pointer-events-none absolute -left-40 -top-40 size-[520px] rounded-full bg-[#efe7da] blur-3xl" />
      <div className="pointer-events-none absolute -bottom-40 -right-40 size-[520px] rounded-full bg-[#e2ece6] blur-3xl" />
      <div className="fade-in relative w-full max-w-md rounded-[28px] border border-line bg-white/90 p-8 shadow-xl backdrop-blur">
        <img src="/favicon.svg" alt="" className="mb-5 size-12" />
        <h1 className="font-display text-3xl">{cfg.site_name}</h1>
        <p className="mt-2 text-sm text-muted">Every piece you own, how you wear it, and pictures of you in it.</p>
        <div className="mt-8 space-y-3">
          {mode === "choose" && (
            <>
              {hasClerk && (
                <Button size="lg" className="w-full" onClick={() => setMode("google")}>
                  <svg viewBox="0 0 24 24" className="size-5">
                    <path fill="#4285F4" d="M22.6 12.2c0-.8-.1-1.5-.2-2.2H12v4.2h6a5 5 0 0 1-2.2 3.3v2.7h3.5c2.1-1.9 3.3-4.7 3.3-8z" />
                    <path fill="#34A853" d="M12 23c3 0 5.5-1 7.3-2.7l-3.5-2.7c-1 .7-2.3 1.1-3.8 1.1-2.9 0-5.4-2-6.3-4.7H2.1v2.8A11 11 0 0 0 12 23z" />
                    <path fill="#FBBC05" d="M5.7 14c-.2-.7-.4-1.3-.4-2s.1-1.4.4-2V7.2H2.1a11 11 0 0 0 0 9.6L5.7 14z" />
                    <path fill="#EA4335" d="M12 5.4c1.6 0 3.1.6 4.2 1.7l3.2-3.2A11 11 0 0 0 2.1 7.2L5.7 10c.9-2.6 3.4-4.6 6.3-4.6z" />
                  </svg>
                  Continue with Google
                </Button>
              )}
              {hasChatGPT && (
                <Button size="lg" className="w-full" onClick={() => setMode("chatgpt")} disabled={!cfg.chatgpt_available}>
                  <Sparkles className="size-5" />
                  Continue with ChatGPT
                </Button>
              )}
              {hasChatGPT && !cfg.chatgpt_available && (
                <p className="text-center text-xs text-muted">ChatGPT sign-in is unavailable while the image worker is offline.</p>
              )}
              {hasPassword && (
                <>
                  {(hasClerk || hasChatGPT) && <div className="py-2 text-center text-xs uppercase tracking-wide text-muted">or</div>}
                  <PasswordSignIn onDone={done} />
                </>
              )}
              {!hasClerk && !hasChatGPT && !hasPassword && <p className="text-sm text-muted">No sign-in method is configured.</p>}
            </>
          )}
          {mode === "google" && cfg.clerk && <ClerkSignIn cfg={cfg.clerk} onDone={done} />}
          {mode === "chatgpt" && (
            <ChatGPTDeviceCode
              start={() => api<LoginState>("/auth/chatgpt/start", { method: "POST" })}
              poll={(id) => api<LoginState>(`/auth/chatgpt/${id}`)}
              doneStatus="signed_in"
              onDone={done}
              purpose="sign in"
            />
          )}
          {mode !== "choose" && (
            <button className="w-full pt-2 text-center text-sm text-muted hover:text-ink" onClick={() => setMode("choose")}>
              ← Other ways to sign in
            </button>
          )}
        </div>
        <p className="mt-8 text-xs leading-relaxed text-muted">Only invited people can sign in. ChatGPT sign-in also connects your ChatGPT plan for AI pictures.</p>
      </div>
    </div>
  );
}
