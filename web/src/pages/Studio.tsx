import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUpToLine, Ban, CheckCircle2, CircleAlert, Clock, Cpu, ImagePlus, Loader2, Pause, Pencil, Play, Plus, RotateCcw, Sparkles, Trash2, UserRound, Wand2, X, Zap,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Job, type Studio as StudioT, type StudioPrefs, type Template } from "../api";
import { useMe } from "../App";
import { ChatGPTConnection } from "../components/ChatGPT";
import { ItemPicker, PhotoPicker } from "../components/Pickers";
import { TemplateIcon } from "../icons";
import { ago, Badge, Button, Card, cx, dur, Field, Input, Modal, Progress, Segmented, Select, Spinner, Textarea, Toggle, useToast } from "../ui";

type QTab = "active" | "done" | "failed" | "cancelled";

const SOURCE: Record<string, string> = { auto: "Auto", manual: "You", agent: "Agent", backfill: "Fill gaps" };

function Stat({ label, value, sub, children }: { label: string; value: React.ReactNode; sub?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="rounded-2xl bg-canvas p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
      {children}
    </div>
  );
}

function JobRow({ j, tpl, selected, onSelect, onCancel, onRetry, onTop, canEdit, canSwitch }: {
  j: Job;
  canSwitch: boolean;
  tpl?: Template;
  selected: boolean;
  onSelect: () => void;
  onCancel: () => void;
  onRetry: (engine?: string) => void;
  onTop: () => void;
  canEdit: boolean;
}) {
  const active = j.status === "queued" || j.status === "running";
  return (
    <div className={cx("flex items-center gap-3 rounded-2xl border bg-white p-2.5 pr-3", selected ? "border-ink" : "border-line")}>
      {canEdit && (j.status === "queued" || j.status === "failed") ? (
        <input type="checkbox" checked={selected} onChange={onSelect} className="size-4 accent-[#1f1d1a]" aria-label="Select" />
      ) : (
        <span className="w-4" />
      )}
      <div className="flex shrink-0 -space-x-3">
        {j.result ? (
          <Link to={`/photo/${j.result_photo_id}`} className="size-14 overflow-hidden rounded-xl bg-canvas">
            <img src={j.result.sm} className="size-full object-cover" alt="" />
          </Link>
        ) : (
          [
            j.base && (
              <div key="base" className="size-14 overflow-hidden rounded-xl border-2 border-white bg-canvas">
                <img src={j.base.sm} className="size-full object-cover" alt="" />
              </div>
            ),
            ...(j.items || []).slice(0, j.base ? 2 : 3).map((it) => (
            <div key={it.id} className="size-14 overflow-hidden rounded-xl border-2 border-white bg-canvas">
              {it.cover && <img src={it.cover.sm} className={cx("size-full", it.cover.cutout ? "object-contain p-1" : "object-cover")} alt="" />}
            </div>
            )),
          ]
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          <TemplateIcon name={tpl?.icon || "sparkles"} className="size-3.5 text-muted" />
          <span className="font-medium">{tpl?.name || j.template}</span>
          <span className="truncate text-muted">· {(j.items || []).map((i) => i.name).join(", ")}</span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">
          {j.status === "running" && (
            <Badge tone="accent">
              <Loader2 className="size-3 animate-spin" /> {j.finishing ? "Finishing touches" : `Making · ${dur(j.elapsed_s)}`}
            </Badge>
          )}
          {j.status === "queued" && <Badge>#{j.position ?? "–"} in queue</Badge>}
          {j.status === "done" && <Badge tone="accent">Done{j.duration_s ? ` · ${dur(j.duration_s)}` : ""}</Badge>}
          {j.status === "failed" && <Badge tone="danger">Failed</Badge>}
          {j.status === "cancelled" && <Badge>Cancelled</Badge>}
          <Badge>{j.engine === "openrouter" ? "OpenRouter" : "ChatGPT"}</Badge>
          <span>{SOURCE[j.source] || j.source}</span>
          <span>· {ago(j.finished_at || j.created_at)}</span>
          {j.cost_usd ? <span>· ${j.cost_usd.toFixed(3)}</span> : null}
          {j.attempts > 1 && <span>· try {j.attempts}</span>}
        </div>
        {j.error && <div className="mt-1 line-clamp-2 text-xs text-danger">{j.error}</div>}
      </div>
      {canEdit && (
        <div className="flex shrink-0 items-center gap-0.5">
          {j.status === "queued" && (
            <Button size="icon" variant="ghost" onClick={onTop} title="Do this next">
              <ArrowUpToLine className="size-4" />
            </Button>
          )}
          {(j.status === "failed" || j.status === "cancelled") && (
            <Button size="icon" variant="ghost" onClick={() => onRetry()} title="Try again">
              <RotateCcw className="size-4" />
            </Button>
          )}
          {canSwitch && (j.status === "failed" || j.status === "queued") && (
            <Button size="icon" variant="ghost" onClick={() => onRetry(j.engine === "openrouter" ? "chatgpt" : "openrouter")} title={`Use ${j.engine === "openrouter" ? "ChatGPT" : "OpenRouter"} instead`}>
              <Cpu className="size-4" />
            </Button>
          )}
          {active && (
            <Button size="icon" variant="ghost" onClick={onCancel} title="Cancel">
              <X className="size-4" />
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

const ICONS = ["sparkles", "shirt", "sun", "user-square", "box", "layout-grid", "party-popper", "smartphone", "aperture", "users", "panels-top-left", "zoom-in"];

function TemplateEditor({ t, onClose }: { t: Partial<Template> | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [v, setV] = useState<Partial<Template>>(t || {});
  useEffect(() => setV(t || {}), [t]);
  const save = useMutation({
    mutationFn: () =>
      v.id ? api(`/studio/templates/${v.id}`, { method: "PATCH", body: v }) : api("/studio/templates", { body: v }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["studio"] });
      toast("Template saved");
      onClose();
    },
    onError: (e: any) => toast(e.message, "error"),
  });
  return (
    <Modal
      open={!!t}
      onClose={onClose}
      title={v.id ? "Edit template" : "New template"}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()} disabled={!v.name || !v.prompt}>
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Name">
          <Input value={v.name || ""} onChange={(e) => setV({ ...v, name: e.target.value })} placeholder="e.g. Me · rooftop at golden hour" />
        </Field>
        <Field label="Short description">
          <Input value={v.description || ""} onChange={(e) => setV({ ...v, description: e.target.value })} />
        </Field>
        <Field label="Icon">
          <div className="flex flex-wrap gap-1.5">
            {ICONS.map((i) => (
              <button key={i} type="button" onClick={() => setV({ ...v, icon: i })} className={cx("grid size-9 place-items-center rounded-xl border", v.icon === i ? "border-ink bg-ink text-paper" : "border-line bg-white")}>
                <TemplateIcon name={i} className="size-4" />
              </button>
            ))}
          </div>
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Toggle checked={!!v.needs_person} onChange={(x) => setV({ ...v, needs_person: x })} label="Puts me in the picture" />
          <Toggle checked={!!v.multi_item} onChange={(x) => setV({ ...v, multi_item: x })} label="Whole outfit (several items)" />
        </div>
        <Field label="Shape">
          <Segmented
            value={(v.aspect as string) || "portrait"}
            onChange={(aspect) => setV({ ...v, aspect })}
            options={[
              { value: "portrait", label: "Portrait 3:4" },
              { value: "square", label: "Square" },
              { value: "landscape", label: "Landscape" },
            ]}
          />
        </Field>
        <Field label="What should the picture look like?" hint={<>Use {"{item}"} for the piece, {"{items}"} for an outfit, {"{setting}"}, {"{light}"} and {"{occasion_scene}"} are filled from the item's season and occasion. Reference-image instructions are added for you.</>}>
          <Textarea rows={5} value={v.prompt || ""} onChange={(e) => setV({ ...v, prompt: e.target.value })} placeholder="The person wearing {item}, walking on a Mumbai street at golden hour, candid street-style photo…" />
        </Field>
      </div>
    </Modal>
  );
}

export default function Studio() {
  const me = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({
    queryKey: ["studio"],
    queryFn: () => api<StudioT>("/studio"),
    refetchInterval: (query) => ((query.state.data?.counts.queued || 0) + (query.state.data?.counts.running || 0) > 0 ? 4000 : 15000),
  });
  const s = q.data;
  const [tab, setTab] = useState<QTab>("active");
  const [sel, setSel] = useState<string[]>([]);
  const [pickFor, setPickFor] = useState<Template | null>(null);
  const [photoPick, setPhotoPick] = useState(false);
  const [editTpl, setEditTpl] = useState<Partial<Template> | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (location.hash === "#model") setTimeout(() => document.getElementById("model")?.scrollIntoView({ behavior: "smooth" }), 300);
  }, [!!s]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["studio"] });
    qc.invalidateQueries({ queryKey: ["me"] });
  };
  const prefs = useMutation({
    mutationFn: (body: Partial<StudioPrefs>) => api<StudioPrefs>("/studio/prefs", { method: "PATCH", body }),
    onMutate: (body) => qc.setQueryData<StudioT>(["studio"], (old) => (old ? { ...old, prefs: { ...old.prefs, ...body } } : old)),
    onSettled: refresh,
    onError: (e: any) => toast(e.message, "error"),
  });
  const post = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: any }) => api(path, { method: "POST", body: body ?? {} }),
    onSuccess: refresh,
    onError: (e: any) => toast(e.message, "error"),
  });

  const tplById = useMemo(() => Object.fromEntries((s?.templates || []).map((t) => [t.id, t])), [s]);
  const jobs = s?.jobs || [];
  const byTab: Record<QTab, Job[]> = {
    active: jobs.filter((j) => j.status === "queued" || j.status === "running"),
    done: jobs.filter((j) => j.status === "done"),
    failed: jobs.filter((j) => j.status === "failed"),
    cancelled: jobs.filter((j) => j.status === "cancelled"),
  };
  const results = byTab.done.filter((j) => j.result).slice(0, 18);

  if (q.isLoading || !s)
    return (
      <div className="flex justify-center py-24">
        <Spinner />
      </div>
    );

  const p = s.prefs;
  const u = s.usage;
  const queued = s.counts.queued || 0;
  const running = s.counts.running || 0;
  const can = me.can_edit;
  const templates = s.templates.filter((t) => !t.tryon); // try-on has its own page
  const groups = Array.from(new Set(templates.map((t) => t.group)));

  const uploadModel = async (files: FileList | null) => {
    if (!files?.length) return;
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f));
    form.append("kind", "worn");
    const r = await api<{ results: { photo_id?: string; error?: string }[] }>("/photos", { form });
    const ids = r.results.map((x) => x.photo_id).filter(Boolean) as string[];
    if (ids.length) prefs.mutate({ model_photo_ids: [...ids, ...p.model_photo_ids].slice(0, 6) });
    const bad = r.results.find((x) => x.error);
    if (bad) toast(bad.error!, "error");
  };
  const toggleAuto = (tid: string, on: boolean) => prefs.mutate({ auto_templates: on ? [...p.auto_templates, tid] : p.auto_templates.filter((x) => x !== tid) });

  const statusLine = p.paused
    ? { icon: <Pause className="size-4" />, text: "Paused — nothing new starts until you resume", tone: "warn" as const }
    : running
      ? { icon: <Loader2 className="size-4 animate-spin" />, text: `Making ${running} picture${running === 1 ? "" : "s"}${queued ? ` · ${queued} waiting` : ""}`, tone: "accent" as const }
      : queued
        ? s.available
          ? { icon: <Clock className="size-4" />, text: `${queued} waiting to start`, tone: "neutral" as const }
          : { icon: <CircleAlert className="size-4" />, text: `${queued} waiting: ${s.reason}`, tone: "warn" as const }
        : { icon: <CheckCircle2 className="size-4" />, text: "Queue is empty", tone: "neutral" as const };

  return (
    <div className="mx-auto max-w-[1400px] px-4 pt-5 sm:px-6 lg:px-8 lg:pt-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl sm:text-4xl">Studio</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">AI pictures of your clothes — on a clean background, or on you. Everything runs through one queue you control.</p>
        </div>
        {can && (
          <div className="flex items-center gap-2">
            <Badge tone={statusLine.tone} className="h-9 gap-1.5 rounded-full px-3 text-[13px]">
              {statusLine.icon} {statusLine.text}
            </Badge>
            <Button variant={p.paused ? "primary" : "secondary"} onClick={() => prefs.mutate({ paused: !p.paused })}>
              {p.paused ? <Play className="size-4" /> : <Pause className="size-4" />} {p.paused ? "Resume" : "Pause"}
            </Button>
          </div>
        )}
      </div>

      {s.warnings.length > 0 && (
        <div className="mt-5 space-y-2">
          {s.warnings.map((w) => (
            <div key={w} className="flex items-start gap-2 rounded-2xl bg-[#fdf3e2] px-4 py-3 text-sm text-warn">
              <CircleAlert className="mt-0.5 size-4 shrink-0" /> {w}
            </div>
          ))}
        </div>
      )}

      {/* usage */}
      <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Today · ChatGPT" value={`${u.chatgpt_today} / ${u.daily_cap}`} sub="your daily limit for this site">
          <Progress className="mt-2 h-1.5" value={u.daily_cap ? u.chatgpt_today / u.daily_cap : 0} tone={u.chatgpt_today >= u.daily_cap ? "warn" : "accent"} />
        </Stat>
        <Stat
          label="Today · OpenRouter"
          value={u.openrouter_configured ? `${u.openrouter_today} / ${u.openrouter_daily_cap}` : "Off"}
          sub={u.openrouter_configured ? `$${u.openrouter_cost_today.toFixed(2)} spent today · ${p.fallback_openrouter || p.engine === "openrouter" ? "in use" : "not used"}` : "No API key on this server"}
        >
          {u.openrouter_configured && <Progress className="mt-2 h-1.5" value={u.openrouter_daily_cap ? u.openrouter_today / u.openrouter_daily_cap : 0} tone="ink" />}
        </Stat>
        <Stat label="Last 7 days" value={u.week} sub={`${u.total} pictures made in total`} />
        <Stat label="Speed" value={u.avg_seconds ? dur(u.avg_seconds) : "—"} sub={`per picture · ${s.worker.online ? `worker online${s.worker.host ? ` (${s.worker.host})` : ""}` : "worker offline"}`} />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-8">
          {/* auto mode + templates */}
          <section>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">Templates</h2>
                <p className="text-sm text-muted">Pick the looks you want for your closet. Templates switched to auto are made for every new item.</p>
              </div>
              {can && (
                <div className="flex items-center gap-3 rounded-full border border-line bg-white py-1.5 pl-4 pr-1.5">
                  <span className="flex items-center gap-1.5 text-sm font-medium">
                    <Zap className={cx("size-4", p.auto_mode ? "text-accent" : "text-muted")} /> Auto mode
                  </span>
                  <Toggle checked={p.auto_mode} onChange={(v) => prefs.mutate({ auto_mode: v })} />
                </div>
              )}
            </div>
            <Link
              to="/tryon"
              className="mb-4 flex items-center gap-3 rounded-2xl border border-line bg-white p-3.5 text-sm hover:border-[#cfc9bf]"
            >
              <span className="grid size-9 place-items-center rounded-xl bg-accent-soft text-accent">
                <TemplateIcon name="replace" className="size-4" />
              </span>
              <span className="flex-1">
                <b className="font-medium">Try on</b>
                <span className="block text-xs text-muted">Put any item on you in one of your own photos, keeping everything else as it is.</span>
              </span>
              <span className="text-muted">→</span>
            </Link>
            {p.auto_mode && p.auto_templates.length > 0 && (
              <p className="mb-3 text-xs text-accent">
                New items get: {p.auto_templates.map((t) => tplById[t]?.name || t).join(", ")}. Use “Fill gaps” to do the same for items you already have.
              </p>
            )}
            {groups.map((g) => (
              <div key={g} className="mb-5">
                <div className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted">{g}</div>
                <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
                  {templates
                    .filter((t) => t.group === g)
                    .map((t) => {
                      const auto = p.auto_templates.includes(t.id);
                      const blocked = t.needs_person && !p.model_photo_ids.length;
                      return (
                        <div key={t.id} className={cx("flex flex-col rounded-2xl border bg-white p-4", auto && p.auto_mode ? "border-accent" : "border-line")}>
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <span className="grid size-8 place-items-center rounded-xl bg-canvas">
                                <TemplateIcon name={t.icon} className="size-4" />
                              </span>
                              <div>
                                <div className="font-medium leading-tight">{t.name}</div>
                                <div className="text-[11px] text-muted">{t.done ? `${t.done} made` : "none yet"}</div>
                              </div>
                            </div>
                            {can && !t.multi_item && (
                              <label className="flex items-center gap-1.5 text-[11px] text-muted" title="Make this for every new item when auto mode is on">
                                Auto
                                <Toggle checked={auto} onChange={(v) => toggleAuto(t.id, v)} />
                              </label>
                            )}
                          </div>
                          <p className="mt-2 text-xs leading-relaxed text-muted">{t.description}</p>
                          <div className="mt-2 flex flex-wrap gap-1">
                            {t.needs_person && (
                              <Badge tone="accent">
                                <UserRound className="size-3" /> You
                              </Badge>
                            )}
                            {t.multi_item && <Badge>Outfit</Badge>}
                            {t.custom && <Badge>Custom</Badge>}
                          </div>
                          {can && (
                            <div className="mt-auto flex flex-wrap gap-1.5 pt-3">
                              <Button size="sm" onClick={() => setPickFor(t)} disabled={blocked}>
                                <Wand2 className="size-3.5" /> Make…
                              </Button>
                              {!t.multi_item && (
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  disabled={blocked}
                                  onClick={async () => {
                                    const r = await api<{ queued: number; skipped: string[] }>("/studio/backfill", { body: { templates: [t.id] } });
                                    toast(r.queued ? `${r.queued} queued for items that don't have one yet` : r.skipped[0] || "Every item already has one");
                                    refresh();
                                  }}
                                >
                                  Fill gaps
                                </Button>
                              )}
                              {t.custom && (
                                <>
                                  <Button size="icon" variant="ghost" onClick={() => setEditTpl(t)} title="Edit">
                                    <Pencil className="size-3.5" />
                                  </Button>
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    title="Delete"
                                    onClick={async () => {
                                      if (!confirm(`Delete template “${t.name}”?`)) return;
                                      await api(`/studio/templates/${t.id}`, { method: "DELETE" });
                                      refresh();
                                    }}
                                  >
                                    <Trash2 className="size-3.5" />
                                  </Button>
                                </>
                              )}
                            </div>
                          )}
                          {blocked && can && <p className="mt-2 text-[11px] text-warn">Needs a model photo of you ↓</p>}
                        </div>
                      );
                    })}
                </div>
              </div>
            ))}
            {can && (
              <Button variant="soft" onClick={() => setEditTpl({ icon: "sparkles", aspect: "portrait", needs_person: true })}>
                <Plus className="size-4" /> New template
              </Button>
            )}
          </section>

          {/* queue */}
          <section>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">Queue</h2>
              <div className="flex flex-wrap items-center gap-2">
                {can && sel.length > 0 && (
                  <>
                    <Button size="sm" onClick={() => post.mutate({ path: "/studio/cancel", body: { ids: sel } }, { onSuccess: () => setSel([]) })}>
                      <Ban className="size-3.5" /> Cancel {sel.length}
                    </Button>
                    {tab === "failed" && (
                      <Button
                        size="sm"
                        onClick={async () => {
                          for (const id of sel) await api(`/studio/jobs/${id}/retry`, { method: "POST", body: {} });
                          setSel([]);
                          refresh();
                        }}
                      >
                        <RotateCcw className="size-3.5" /> Retry {sel.length}
                      </Button>
                    )}
                  </>
                )}
                {can && tab === "active" && queued > 0 && sel.length === 0 && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => confirm(`Cancel all ${queued} waiting pictures?`) && post.mutate({ path: "/studio/cancel", body: { all_queued: true } })}
                  >
                    Cancel all waiting
                  </Button>
                )}
                {can && tab !== "active" && byTab[tab].length > 0 && (
                  <Button size="sm" variant="ghost" onClick={() => post.mutate({ path: "/studio/clear" })} title="Remove finished, failed and cancelled entries from the list (pictures are kept)">
                    Clear list
                  </Button>
                )}
              </div>
            </div>
            <Segmented<QTab>
              value={tab}
              onChange={(t) => {
                setTab(t);
                setSel([]);
              }}
              options={[
                { value: "active", label: `Active ${byTab.active.length}` },
                { value: "done", label: `Done ${byTab.done.length}` },
                { value: "failed", label: `Failed ${byTab.failed.length}` },
                { value: "cancelled", label: `Cancelled ${byTab.cancelled.length}` },
              ]}
            />
            <div className="mt-3 space-y-2">
              {byTab[tab].length === 0 ? (
                <div className="rounded-2xl border border-dashed border-line py-10 text-center text-sm text-muted">
                  {tab === "active" ? "Nothing waiting. Pick a template above, or use “AI pictures” on any item." : "Nothing here."}
                </div>
              ) : (
                byTab[tab].map((j) => (
                  <JobRow
                    key={j.id}
                    j={j}
                    tpl={tplById[j.template]}
                    canEdit={can}
                    canSwitch={u.openrouter_configured}
                    selected={sel.includes(j.id)}
                    onSelect={() => setSel((x) => (x.includes(j.id) ? x.filter((i) => i !== j.id) : [...x, j.id]))}
                    onCancel={() => post.mutate({ path: "/studio/cancel", body: { ids: [j.id] } })}
                    onRetry={(engine) => post.mutate({ path: `/studio/jobs/${j.id}/retry`, body: engine ? { engine } : {} })}
                    onTop={() => post.mutate({ path: `/studio/jobs/${j.id}/top` })}
                  />
                ))
              )}
            </div>
          </section>

          {results.length > 0 && (
            <section>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-lg font-semibold">Latest pictures</h2>
                <Link to="/?view=photos&source=ai" className="text-sm text-muted hover:text-ink">
                  See all
                </Link>
              </div>
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6">
                {results.map((j) => (
                  <Link key={j.id} to={`/photo/${j.result_photo_id}`} className="group relative aspect-[3/4] overflow-hidden rounded-xl bg-canvas">
                    <img src={j.result!.md} className="size-full object-cover transition-transform group-hover:scale-[1.03]" alt="" />
                    <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/60 to-transparent p-1.5 text-[10px] text-white">{tplById[j.template]?.name}</span>
                  </Link>
                ))}
              </div>
            </section>
          )}
        </div>

        {/* right rail */}
        <div className="space-y-4 pb-10">
          <ChatGPTConnection />

          <Card className="p-5" >
            <div id="model" className="scroll-mt-20" />
            <div className="flex items-center justify-between">
              <div className="font-medium">Model photo of you</div>
              <Badge>{p.model_photo_ids.length}/6</Badge>
            </div>
            <p className="mt-1 text-sm text-muted">Pictures with “You” use these to keep your face and build. A clear, well-lit, full-length photo works best.</p>
            {s.model_photos.length > 0 ? (
              <div className="mt-3 grid grid-cols-3 gap-2">
                {s.model_photos.map((m, i) => (
                  <div key={m.id} className="group relative aspect-[3/4] overflow-hidden rounded-xl bg-canvas">
                    <img src={m.image.sm} className="size-full object-cover" alt="" />
                    {i === 0 && <span className="absolute left-1 top-1 rounded bg-ink px-1 text-[10px] text-paper">Main</span>}
                    {can && (
                      <div className="absolute inset-x-1 bottom-1 hidden gap-1 group-hover:flex">
                        {i > 0 && (
                          <button className="flex-1 rounded bg-white/90 py-0.5 text-[10px]" onClick={() => prefs.mutate({ model_photo_ids: [m.id, ...p.model_photo_ids.filter((x) => x !== m.id)] })}>
                            Main
                          </button>
                        )}
                        <button className="rounded bg-white/90 px-1.5 py-0.5" onClick={() => prefs.mutate({ model_photo_ids: p.model_photo_ids.filter((x) => x !== m.id) })} aria-label="Remove">
                          <X className="size-3" />
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="mt-3 rounded-xl bg-[#fdf3e2] p-3 text-xs text-warn">No model photo yet — “You” templates are paused until you add one.</div>
            )}
            {can && (
              <div className="mt-3 flex flex-wrap gap-2">
                <Button size="sm" onClick={() => uploadRef.current?.click()}>
                  <ImagePlus className="size-3.5" /> Upload
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setPhotoPick(true)}>
                  <UserRound className="size-3.5" /> From my photos
                </Button>
                <input ref={uploadRef} type="file" accept="image/*,.heic,.heif" className="hidden" onChange={(e) => uploadModel(e.target.files)} />
              </div>
            )}
          </Card>

          {can && (
            <Card className="space-y-4 p-5">
              <div className="font-medium">Generation settings</div>
              <Field label="Make pictures with">
                <Select
                  value={p.engine}
                  onChange={(engine) => prefs.mutate({ engine })}
                  options={[
                    { value: "chatgpt", label: "My ChatGPT plan (GPT image)" },
                    { value: "openrouter", label: "OpenRouter (pay per picture)", disabled: !u.openrouter_configured },
                  ]}
                />
              </Field>
              <Field label="Daily limit (ChatGPT)" hint="Stops this site from using up your whole ChatGPT allowance.">
                <Input type="number" min={0} max={1000} defaultValue={p.daily_cap} onBlur={(e) => Number(e.target.value) !== p.daily_cap && prefs.mutate({ daily_cap: Number(e.target.value) })} />
              </Field>
              <Field label="Seconds between pictures" hint="Spacing keeps you well inside ChatGPT's rate limits.">
                <Input type="number" min={0} max={1000} defaultValue={p.min_interval_s} onBlur={(e) => Number(e.target.value) !== p.min_interval_s && prefs.mutate({ min_interval_s: Number(e.target.value) })} />
              </Field>
              {u.openrouter_configured && (
                <>
                  <Toggle checked={p.fallback_openrouter} onChange={(v) => prefs.mutate({ fallback_openrouter: v })} label="Use OpenRouter when ChatGPT hits its limit" />
                  <Field label="Daily limit (OpenRouter)">
                    <Input
                      type="number"
                      min={0}
                      max={1000}
                      defaultValue={p.openrouter_daily_cap}
                      onBlur={(e) => Number(e.target.value) !== p.openrouter_daily_cap && prefs.mutate({ openrouter_daily_cap: Number(e.target.value) })}
                    />
                  </Field>
                </>
              )}
            </Card>
          )}

          <div className="rounded-2xl bg-canvas p-4 text-xs leading-relaxed text-muted">
            <Sparkles className="mb-1 size-4" />
            Pictures are made one at a time by your own ChatGPT account through a worker on the server, so they never cost per image. AI pictures are always labelled and kept
            separate from real photos — filter them with “Real photos” in your closet.
          </div>
        </div>
      </div>

      {pickFor && (
        <ItemPicker
          open
          onClose={() => setPickFor(null)}
          title={pickFor.multi_item ? `${pickFor.name}: choose the outfit (2–5 pieces)` : `${pickFor.name}: choose items`}
          max={pickFor.multi_item ? 5 : 50}
          onPick={async (ids) => {
            const t = pickFor;
            try {
              const r = await api<{ jobs: Job[] }>("/studio/jobs", { body: { template: t.id, item_ids: ids } });
              toast(`${r.jobs.length} queued`);
              setTab("active");
              refresh();
            } catch (e: any) {
              toast(e.message, "error");
            }
          }}
        />
      )}
      <PhotoPicker open={photoPick} onClose={() => setPhotoPick(false)} title="Choose a photo of you" query={{ kind: "worn", source: "real" }} onPick={(ph) => prefs.mutate({ model_photo_ids: [ph.id, ...p.model_photo_ids].slice(0, 6) })} />
      <TemplateEditor t={editTpl} onClose={() => setEditTpl(null)} />
    </div>
  );
}

