import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, Copy, ExternalLink, Link2, Unlink } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type Account, type LoginState } from "../api";
import { Badge, Button, Card, Modal, Progress, Spinner, useToast, when } from "../ui";

/** Shows the one-time code from `codex login --device-auth` and waits for approval. */
export function ChatGPTDeviceCode({ start, poll, doneStatus, onDone, purpose }: {
  start: () => Promise<LoginState>;
  poll: (id: string) => Promise<LoginState>;
  doneStatus: string;
  onDone: () => void;
  purpose: string;
}) {
  const [st, setSt] = useState<LoginState | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const started = useRef(false);
  const toast = useToast();

  const begin = async () => {
    setError("");
    setSt(null);
    try {
      setSt(await start());
    } catch (e: any) {
      setError(e.message);
    }
  };
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    begin();
  }, []);
  useEffect(() => {
    if (!st || ["approved", "signed_in", "consumed", "rejected", "failed", "expired"].includes(st.status)) {
      if (st && st.status === doneStatus) onDone();
      return;
    }
    const t = setTimeout(async () => {
      try {
        setSt(await poll(st.id));
      } catch (e: any) {
        setError(e.message);
      }
    }, 2000);
    return () => clearTimeout(t);
  }, [st]);

  if (error)
    return (
      <div className="space-y-3">
        <div className="flex gap-2 rounded-xl bg-[#fdecea] p-3 text-sm text-danger">
          <CircleAlert className="mt-0.5 size-4 shrink-0" />
          {error}
        </div>
        <Button className="w-full" onClick={begin}>
          Try again
        </Button>
      </div>
    );
  if (!st || st.status === "pending")
    return (
      <div className="flex flex-col items-center gap-3 py-6 text-sm text-muted">
        <Spinner />
        Asking ChatGPT for a sign-in code…
      </div>
    );
  if (["rejected", "failed", "expired"].includes(st.status))
    return (
      <div className="space-y-3">
        <div className="flex gap-2 rounded-xl bg-[#fdecea] p-3 text-sm text-danger">
          <CircleAlert className="mt-0.5 size-4 shrink-0" />
          {st.message || (st.status === "expired" ? "The code expired." : "Sign-in did not complete.")}
        </div>
        <Button className="w-full" onClick={begin}>
          Get a new code
        </Button>
      </div>
    );
  if (st.status === doneStatus || st.status === "approved" || st.status === "consumed")
    return (
      <div className="flex flex-col items-center gap-2 py-6 text-sm">
        <CircleCheck className="size-8 text-accent" />
        Connected as <b>{st.email}</b>
      </div>
    );
  return (
    <div className="space-y-4">
      <ol className="space-y-4 text-sm">
        <li className="flex gap-3">
          <span className="grid size-6 shrink-0 place-items-center rounded-full bg-ink text-xs text-paper">1</span>
          <div className="flex-1">
            Open ChatGPT's device page and sign in with your <b>personal</b> ChatGPT account.
            <a href={st.verification_url || "#"} target="_blank" rel="noreferrer" className="mt-2 flex">
              <Button variant="primary" className="w-full">
                Open {st.verification_url?.replace("https://", "")} <ExternalLink className="size-4" />
              </Button>
            </a>
          </div>
        </li>
        <li className="flex gap-3">
          <span className="grid size-6 shrink-0 place-items-center rounded-full bg-ink text-xs text-paper">2</span>
          <div className="flex-1">
            Enter this one-time code:
            <button
              className="mt-2 flex w-full items-center justify-center gap-3 rounded-2xl border border-dashed border-[#cfc9bf] bg-canvas py-4 font-mono text-2xl tracking-[0.2em]"
              onClick={async () => {
                await navigator.clipboard.writeText(st.user_code || "");
                setCopied(true);
                toast("Code copied");
              }}
            >
              {st.user_code}
              <Copy className={copied ? "size-4 text-accent" : "size-4 text-muted"} />
            </button>
          </div>
        </li>
      </ol>
      <div className="flex items-center gap-2 text-xs text-muted">
        <Spinner className="size-3.5" /> Waiting for you to approve, to {purpose}. The code expires in 15 minutes.
      </div>
      <p className="rounded-xl bg-[#fdf3e2] p-3 text-xs leading-relaxed text-warn">
        Only enter this code because you started it here. Never enter a code someone else sent you.
      </p>
    </div>
  );
}

function LimitBar({ label, w }: { label: string; w?: { used_percent: number | null; window_minutes: number | null; resets_at: number | null } | null }) {
  if (!w || w.used_percent === null || w.used_percent === undefined) return null;
  const pct = Math.round(w.used_percent);
  const span = w.window_minutes ? (w.window_minutes >= 1440 ? `${Math.round(w.window_minutes / 1440)}-day` : `${Math.round(w.window_minutes / 60)}-hour`) : "";
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="text-ink-2">
          {label} {span && <span className="text-muted">({span} window)</span>}
        </span>
        <span className="tabular-nums text-muted">
          {pct}% used{w.resets_at ? ` · resets ${when(w.resets_at)}` : ""}
        </span>
      </div>
      <Progress value={pct} tone={pct >= 90 ? "danger" : pct >= 70 ? "warn" : "accent"} />
    </div>
  );
}

export function PlanLimits({ account }: { account: Account }) {
  const l = account.limits || {};
  if (!l.primary && !l.secondary) return null;
  return (
    <div className="space-y-3">
      <LimitBar label="Short-term limit" w={l.primary} />
      <LimitBar label="Weekly limit" w={l.secondary} />
    </div>
  );
}

/** ChatGPT connection card for Studio and Settings. */
export function ChatGPTConnection({ compact }: { compact?: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["chatgpt"], queryFn: () => api<{ account: Account; worker: { online: boolean } }>("/chatgpt"), refetchInterval: 15000 });
  const [open, setOpen] = useState(false);
  if (!q.data) return <Spinner />;
  const { account, worker } = q.data;
  const connected = ["connected", "limited"].includes(account.status);
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 font-medium">
            ChatGPT
            {connected ? (
              <Badge tone={account.status === "limited" ? "warn" : "accent"}>{account.status === "limited" ? "Limit reached" : "Connected"}</Badge>
            ) : account.status === "pending" ? (
              <Badge>Waiting for sign-in</Badge>
            ) : account.status === "error" ? (
              <Badge tone="danger">Needs attention</Badge>
            ) : (
              <Badge>Not connected</Badge>
            )}
            {!worker.online && <Badge tone="warn">Worker offline</Badge>}
          </div>
          <p className="mt-1 text-sm text-muted">
            {connected
              ? `${account.email}${account.plan ? ` · ${account.plan} plan` : ""}`
              : "AI pictures use your own ChatGPT plan. Connect it once; nothing is shared with anyone else."}
          </p>
          {account.message && account.status !== "connected" && <p className="mt-1 text-sm text-warn">{account.message}</p>}
        </div>
        <div className="flex gap-2">
          {connected ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={async () => {
                if (!confirm("Disconnect ChatGPT? Queued pictures will wait until you connect again.")) return;
                await api("/chatgpt/disconnect", { method: "POST" });
                toast("Disconnecting ChatGPT");
                qc.invalidateQueries();
              }}
            >
              <Unlink className="size-4" /> Disconnect
            </Button>
          ) : (
            <Button variant="primary" size="sm" onClick={() => setOpen(true)} disabled={!worker.online}>
              <Link2 className="size-4" /> Connect ChatGPT
            </Button>
          )}
        </div>
      </div>
      {connected && !compact && (
        <div className="mt-4">
          <PlanLimits account={account} />
        </div>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="Connect ChatGPT">
        {open && (
          <ChatGPTDeviceCode
            start={() => api<LoginState>("/chatgpt/connect", { method: "POST" })}
            poll={(id) => api<LoginState>(`/chatgpt/connect/${id}`)}
            doneStatus="approved"
            purpose="connect it for pictures"
            onDone={() => {
              setTimeout(() => {
                setOpen(false);
                qc.invalidateQueries();
                toast("ChatGPT connected");
              }, 1200);
            }}
          />
        )}
      </Modal>
    </Card>
  );
}
