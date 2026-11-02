import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Check, Copy, KeyRound, LogOut, Plus, Trash2, Users } from "lucide-react";
import { useState } from "react";
import { api, setActiveWardrobe, type User } from "../api";
import { useMe } from "../App";
import { ChatGPTConnection } from "../components/ChatGPT";
import { ago, Badge, Button, Card, Chip, Field, Input, Modal, Segmented, Toggle, useToast, when } from "../ui";

type Token = { id: string; label: string; prefix: string; scopes: string; created_at: number; last_used_at: number | null; revoked_at: number | null };
type AuditRow = { id: number; actor: string; action: string; target_id: string | null; detail: any; created_at: number };

function CopyBlock({ text, label }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="relative">
      {label && <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{label}</div>}
      <pre className="overflow-x-auto rounded-xl bg-ink p-3 pr-12 text-[12px] leading-relaxed text-paper scrollbar-thin">{text}</pre>
      <button
        className="absolute bottom-2 right-2 rounded-lg bg-white/10 p-1.5 text-paper hover:bg-white/20"
        onClick={() => {
          navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        }}
        aria-label="Copy"
      >
        {done ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </button>
    </div>
  );
}

function Agents() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["tokens"], queryFn: () => api<{ tokens: Token[] }>("/tokens") });
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("Claude Code");
  const [readOnly, setReadOnly] = useState(false);
  const [created, setCreated] = useState<string | null>(null);
  const origin = location.origin;
  const create = useMutation({
    mutationFn: () => api<Token & { token: string }>("/tokens", { body: { label, read_only: readOnly } }),
    onSuccess: (t) => {
      setCreated(t.token);
      qc.invalidateQueries({ queryKey: ["tokens"] });
    },
    onError: (e: any) => toast(e.message, "error"),
  });
  const live = (q.data?.tokens || []).filter((t) => !t.revoked_at);
  const tok = created || "wd_…";
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 font-medium">
            <Bot className="size-4" /> Agents (MCP & API)
          </div>
          <p className="mt-1 max-w-xl text-sm text-muted">
            Let Claude, Codex or any MCP client search your closet, import photo folders, fix details and queue AI pictures. Each agent gets its own revocable token, and every change
            it makes is logged.
          </p>
        </div>
        <Button
          variant="primary"
          size="sm"
          onClick={() => {
            setCreated(null);
            setOpen(true);
          }}
        >
          <Plus className="size-4" /> Connect an agent
        </Button>
      </div>
      {live.length > 0 && (
        <ul className="mt-4 divide-y divide-line rounded-xl border border-line">
          {live.map((t) => (
            <li key={t.id} className="flex items-center gap-3 px-3 py-2.5 text-sm">
              <KeyRound className="size-4 text-muted" />
              <div className="min-w-0 flex-1">
                <div className="font-medium">{t.label}</div>
                <div className="text-xs text-muted">
                  {t.prefix}… · {t.scopes === "read" ? "read only" : "read & write"} · {t.last_used_at ? `used ${ago(t.last_used_at)}` : "never used"}
                </div>
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={async () => {
                  if (!confirm(`Revoke “${t.label}”? That agent loses access immediately.`)) return;
                  await api(`/tokens/${t.id}`, { method: "DELETE" });
                  qc.invalidateQueries({ queryKey: ["tokens"] });
                }}
              >
                Revoke
              </Button>
            </li>
          ))}
        </ul>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="Connect an agent" wide>
        {!created ? (
          <div className="space-y-4">
            <Field label="Name">
              <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Claude Code on my laptop" />
            </Field>
            <Toggle checked={readOnly} onChange={setReadOnly} label="Read only (can search and look, but not change anything)" />
            <Button variant="primary" loading={create.isPending} onClick={() => create.mutate()} disabled={!label.trim()}>
              Create token
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="rounded-xl bg-[#fdf3e2] p-3 text-sm text-warn">Copy the token now — it is shown only once. Anyone with it can act on your wardrobe.</div>
            <CopyBlock label="Token" text={tok} />
            <CopyBlock label="Claude Code" text={`claude mcp add --transport http wardrobe ${origin}/mcp \\\n  --header "Authorization: Bearer ${tok}"`} />
            <CopyBlock
              label="Codex (~/.codex/config.toml)"
              text={`[mcp_servers.wardrobe]\nurl = "${origin}/mcp"\nbearer_token_env_var = "WARDROBE_TOKEN"\n\n# then: export WARDROBE_TOKEN=${tok}`}
            />
            <CopyBlock label="Plain HTTP" text={`curl -H "Authorization: Bearer ${tok}" "${origin}/api/v1/items?season=winter&color=navy"`} />
            <p className="text-xs text-muted">
              Agent guide: <a className="underline" href="/llms.txt" target="_blank">{origin}/llms.txt</a>. The repo also ships a <code>wardrobe</code> skill for Claude Code and Codex.
            </p>
          </div>
        )}
      </Modal>
    </Card>
  );
}

function Members() {
  const me = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["members"], queryFn: () => api<{ members: User[]; my_shares: { member_id: string; can_edit: boolean }[] }>("/members") });
  const [email, setEmail] = useState("");
  const owner = me.user.role === "owner";
  const invite = useMutation({
    mutationFn: () => api("/members", { body: { email } }),
    onSuccess: () => {
      setEmail("");
      qc.invalidateQueries({ queryKey: ["members"] });
      toast("Invited — they can now sign in with that email");
    },
    onError: (e: any) => toast(e.message, "error"),
  });
  const others = (q.data?.members || []).filter((m) => m.id !== me.user.id && m.status !== "disabled");
  const level = (id: string) => {
    const sh = q.data?.my_shares.find((x) => x.member_id === id);
    return sh ? (sh.can_edit ? "edit" : "view") : "none";
  };
  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 font-medium">
        <Users className="size-4" /> People
      </div>
      <p className="mt-1 text-sm text-muted">Everyone has their own wardrobe. Share yours with a partner or stylist to let them browse — or help edit.</p>
      {owner && (
        <div className="mt-4 flex gap-2">
          <Input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="email@example.com" type="email" />
          <Button onClick={() => invite.mutate()} loading={invite.isPending} disabled={!email.includes("@")}>
            Invite
          </Button>
        </div>
      )}
      {others.length > 0 && (
        <ul className="mt-4 divide-y divide-line rounded-xl border border-line">
          {others.map((m) => (
            <li key={m.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5 text-sm">
              <div className="min-w-0 flex-1">
                <div className="font-medium">{m.name || m.email}</div>
                <div className="text-xs text-muted">
                  {m.email} {m.status === "invited" && <Badge>Invited</Badge>}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted">My closet:</span>
                <Segmented
                  value={level(m.id)}
                  onChange={async (lv) => {
                    await api(`/shares/${m.id}`, { method: "PUT", body: { level: lv } });
                    qc.invalidateQueries({ queryKey: ["members"] });
                  }}
                  options={[
                    { value: "none", label: "Private" },
                    { value: "view", label: "Can view" },
                    { value: "edit", label: "Can edit" },
                  ]}
                />
                {owner && (
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={async () => {
                      if (!confirm(`Remove ${m.email}? They lose access and their sessions end.`)) return;
                      await api(`/members/${m.id}`, { method: "DELETE" });
                      qc.invalidateQueries({ queryKey: ["members"] });
                    }}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Occasions() {
  const me = useMe();
  const qc = useQueryClient();
  const [v, setV] = useState("");
  const custom = me.taxonomy.occasions.filter((o) => !BASE_OCCASIONS.has(o));
  const save = async (list: string[]) => {
    await api("/prefs", { method: "PATCH", body: { occasions: list } });
    qc.invalidateQueries({ queryKey: ["me"] });
  };
  return (
    <Card className="p-5">
      <div className="font-medium">Your occasions</div>
      <p className="mt-1 text-sm text-muted">Add the events you dress for — they show up as filters and help the AI tag new pieces.</p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {me.taxonomy.occasions.map((o) => (
          <Chip key={o} active={custom.includes(o)} onRemove={custom.includes(o) ? () => save(custom.filter((x) => x !== o)) : undefined}>
            {o}
          </Chip>
        ))}
      </div>
      {me.can_edit && (
        <form
          className="mt-3 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (v.trim()) save([...custom, v.trim().toLowerCase()]);
            setV("");
          }}
        >
          <Input value={v} onChange={(e) => setV(e.target.value)} placeholder="e.g. sangeet, office offsite, trek" />
          <Button type="submit">Add</Button>
        </form>
      )}
    </Card>
  );
}

// keep in sync with OCCASIONS in server/wardrobe/taxonomy.py
const BASE_OCCASIONS = new Set(["casual", "office", "formal", "party", "wedding", "festive", "ethnic", "sport", "travel", "lounge", "date", "outdoor"]);

function Audit() {
  const q = useQuery({ queryKey: ["audit"], queryFn: () => api<{ events: AuditRow[] }>("/audit", { query: { limit: 60 } }) });
  return (
    <Card className="p-5">
      <div className="font-medium">Activity</div>
      <p className="mt-1 text-sm text-muted">Every change, by you or an agent.</p>
      <ul className="mt-3 max-h-80 space-y-1.5 overflow-y-auto pr-1 text-xs scrollbar-thin">
        {(q.data?.events || []).map((e) => (
          <li key={e.id} className="flex gap-2">
            <span className="w-28 shrink-0 text-muted">{when(e.created_at)}</span>
            <span className="min-w-0 flex-1 truncate">
              <b className="font-medium">{e.action.replace(/_/g, " ")}</b>
              {e.detail?.name ? ` · ${e.detail.name}` : ""}
            </span>
            <span className="shrink-0 text-muted">{e.actor.startsWith("agent:") ? e.actor.split(":")[1] : e.actor.startsWith("web:") ? "you" : e.actor}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export default function Settings() {
  const me = useMe();
  const qc = useQueryClient();
  const logout = async () => {
    await api("/auth/logout", { method: "POST" });
    setActiveWardrobe("");
    qc.clear();
    location.href = "/";
  };
  return (
    <div className="mx-auto max-w-3xl px-4 pt-5 sm:px-6 lg:px-8 lg:pt-8">
      <h1 className="font-display text-3xl sm:text-4xl">Settings</h1>
      <div className="mt-6 space-y-4 pb-12">
        <Card className="flex flex-wrap items-center gap-4 p-5">
          <div className="grid size-12 place-items-center overflow-hidden rounded-full bg-canvas text-lg font-medium">
            {me.user.avatar_url ? <img src={me.user.avatar_url} className="size-full object-cover" alt="" /> : (me.user.name || me.user.email)[0].toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <div className="font-medium">{me.user.name || me.user.email}</div>
            <div className="text-sm text-muted">
              {me.user.email} · signed in with {me.via === "chatgpt" ? "ChatGPT" : me.via === "clerk" ? "Google" : me.via}
            </div>
          </div>
          <Button variant="ghost" onClick={logout}>
            <LogOut className="size-4" /> Sign out
          </Button>
        </Card>
        <ChatGPTConnection />
        <Agents />
        <Members />
        <Occasions />
        <Audit />
      </div>
    </div>
  );
}
