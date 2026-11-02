import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Combine, Inbox as InboxIcon, Link2, Pencil, Plus, Receipt, RefreshCw, Tag, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Batch, type BatchView, type Proposal } from "../api";
import { useMe } from "../App";
import { ItemFields, type Draft } from "../components/ItemForm";
import { ItemPicker } from "../components/Pickers";
import { ago, Badge, Button, cap, Card, cx, Empty, money, Modal, Progress, Spinner, Swatch, useToast } from "../ui";

const STATUS: Record<string, { label: string; tone: "neutral" | "accent" | "warn" | "danger" | "dark" }> = {
  open: { label: "Uploading", tone: "neutral" },
  analyzing: { label: "Looking at photos", tone: "accent" },
  grouping: { label: "Matching pieces", tone: "accent" },
  review: { label: "Ready to review", tone: "warn" },
  done: { label: "Done", tone: "neutral" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export default function Inbox() {
  const q = useQuery({ queryKey: ["batches"], queryFn: () => api<{ batches: Batch[] }>("/batches"), refetchInterval: 5000 });
  const batches = q.data?.batches || [];
  return (
    <div className="mx-auto max-w-4xl px-4 pt-5 sm:px-6 lg:px-8 lg:pt-8">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl sm:text-4xl">Review</h1>
          <p className="mt-1 text-sm text-muted">Imports land here. Check what was found, fix anything off, then add it to your closet.</p>
        </div>
        <Link to="/upload">
          <Button variant="primary">
            <Plus className="size-4" /> Add photos
          </Button>
        </Link>
      </div>
      <div className="mt-6 space-y-2 pb-10">
        {q.isLoading ? (
          <div className="flex justify-center py-16">
            <Spinner />
          </div>
        ) : batches.length === 0 ? (
          <Empty icon={<InboxIcon className="size-6" />} title="Nothing to review">
            Imports from the web app or your agents appear here.
          </Empty>
        ) : (
          batches.map((b) => {
            const st = STATUS[b.status] || { label: b.status, tone: "neutral" as const };
            const pending = b.proposal_counts.pending || 0;
            return (
              <Link key={b.id} to={`/inbox/${b.id}`} className="flex items-center gap-4 rounded-2xl border border-line bg-white p-3 transition-colors hover:border-[#cfc9bf]">
                <div className="size-16 shrink-0 overflow-hidden rounded-xl bg-canvas">{b.cover && <img src={`/media/${b.cover}/sm`} className="size-full object-cover" alt="" />}</div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{b.photos} photos</span>
                    <Badge tone={st.tone}>{st.label}</Badge>
                    {b.created_by?.startsWith("agent:") && <Badge>via {b.created_by.split(":")[1]}</Badge>}
                  </div>
                  <div className="mt-0.5 truncate text-sm text-muted">{b.message || b.note || "Import"}</div>
                </div>
                <div className="text-right text-xs text-muted">
                  {pending > 0 && <div className="font-medium text-ink">{pending} to review</div>}
                  {b.proposal_counts.accepted ? <div>{b.proposal_counts.accepted} added</div> : null}
                  <div>{ago(b.created_at)}</div>
                </div>
              </Link>
            );
          })
        )}
      </div>
    </div>
  );
}

function ProposalCard({ p, selected, onSelect, onEdit, onAccept, onReject, busy }: {
  p: Proposal;
  selected: boolean;
  onSelect: () => void;
  onEdit: () => void;
  onAccept: () => void;
  onReject: () => void;
  busy: boolean;
}) {
  const d = p.data;
  const tags = p.links.filter((l) => l.role === "tag").length;
  const receipts = p.links.filter((l) => l.role === "receipt").length;
  const conf = p.confidence ?? 0;
  const decided = p.status !== "pending";
  return (
    <div className={cx("overflow-hidden rounded-2xl border bg-white", selected ? "border-ink" : "border-line", decided && "opacity-60")}>
      <div className="relative aspect-square bg-canvas">
        {p.preview ? <img src={p.preview.md} className={cx("size-full", p.preview.cutout ? "object-contain p-4" : "object-cover")} alt="" /> : null}
        {!decided && (
          <button
            onClick={onSelect}
            className={cx("absolute left-2 top-2 grid size-6 place-items-center rounded-full border-2", selected ? "border-ink bg-ink text-paper" : "border-white bg-white/70")}
            aria-label="Select"
          >
            {selected && <Check className="size-3.5" />}
          </button>
        )}
        <div className="absolute right-2 top-2 flex gap-1">
          {p.match ? <Badge tone="accent">Already have</Badge> : <Badge tone="dark">New</Badge>}
        </div>
        <div className="absolute bottom-2 left-2 flex gap-1">
          {p.links
            .filter((l) => l.role !== "tag" && l.role !== "receipt")
            .slice(0, 4)
            .map((l, i) => (
              <img key={i} src={(l.crop || l.photo)?.sm} className="size-8 rounded-md border-2 border-white object-cover" alt="" />
            ))}
        </div>
      </div>
      <div className="p-3">
        <div className="truncate font-medium">{d.name || "Unnamed"}</div>
        <div className="mt-0.5 truncate text-xs text-muted">{[d.brand, cap(d.subcategory || d.category)].filter(Boolean).join(" · ") || " "}</div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {(d.colors || []).slice(0, 4).map((c: any) => (
            <Swatch key={c.name} hex={c.hex} size={14} />
          ))}
          {d.price != null && <span className="text-xs">{money(d.price, d.currency)}</span>}
          {tags > 0 && (
            <span className="inline-flex items-center gap-0.5 text-xs text-muted">
              <Tag className="size-3" />
              {tags}
            </span>
          )}
          {receipts > 0 && (
            <span className="inline-flex items-center gap-0.5 text-xs text-muted">
              <Receipt className="size-3" />
              {receipts}
            </span>
          )}
        </div>
        {p.match && <div className="mt-2 truncate text-xs text-accent">Adds photos to “{p.match.name}”</div>}
        <div className="mt-2">
          <Progress value={conf} tone={conf >= 0.7 ? "accent" : conf >= 0.45 ? "warn" : "danger"} className="h-1" />
          <div className="mt-1 text-[11px] text-muted">{Math.round(conf * 100)}% sure</div>
        </div>
        {decided ? (
          <div className="mt-3 text-xs">
            {p.status === "accepted" && p.item_id ? (
              <Link className="font-medium text-accent hover:underline" to={`/item/${p.item_id}`}>
                Added — open item
              </Link>
            ) : (
              <span className="text-muted">{cap(p.status)}</span>
            )}
          </div>
        ) : (
          <div className="mt-3 flex gap-1.5">
            <Button size="sm" variant="primary" className="flex-1" onClick={onAccept} disabled={busy}>
              <Check className="size-3.5" /> Add
            </Button>
            <Button size="sm" onClick={onEdit} aria-label="Edit">
              <Pencil className="size-3.5" />
            </Button>
            <Button size="sm" variant="ghost" onClick={onReject} aria-label="Skip" disabled={busy}>
              <X className="size-3.5" />
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function EditProposal({ p, onClose }: { p: Proposal; onClose: () => void }) {
  const me = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const [draft, setDraft] = useState<Draft>(p.data as Draft);
  const [matchPick, setMatchPick] = useState(false);
  const [match, setMatch] = useState<{ id: string; name: string } | null>(p.match);
  const save = useMutation({
    mutationFn: () => {
      const { provenance, ...data } = draft as any;
      return api(`/proposals/${p.id}`, { method: "PATCH", body: { data, match_item_id: match?.id || null } });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["batch", p.batch_id] });
      onClose();
    },
    onError: (e: any) => toast(e.message, "error"),
  });
  return (
    <Modal
      open
      onClose={onClose}
      wide
      title="Edit before adding"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
            Save
          </Button>
        </>
      }
    >
      <div className="grid gap-6 md:grid-cols-[220px_minmax(0,1fr)]">
        <div className="space-y-2">
          {p.links.map((l, i) => (
            <div key={i} className="overflow-hidden rounded-xl bg-canvas">
              <img src={(l.cutout || l.crop || l.photo)?.md} className="w-full object-contain" alt="" />
              <div className="px-2 py-1 text-[11px] text-muted">{cap(l.role)}</div>
            </div>
          ))}
        </div>
        <div className="space-y-5">
          <div className="rounded-2xl bg-canvas p-3 text-sm">
            {match ? (
              <div className="flex items-center justify-between gap-2">
                <span>
                  Same as <b>{match.name}</b> — photos will be added to it.
                </span>
                <Button size="sm" variant="ghost" onClick={() => setMatch(null)}>
                  It's a new item
                </Button>
              </div>
            ) : (
              <div className="flex items-center justify-between gap-2">
                <span>This will be a new item.</span>
                <Button size="sm" onClick={() => setMatchPick(true)}>
                  <Link2 className="size-3.5" /> I already have it
                </Button>
              </div>
            )}
            {p.reason && <p className="mt-2 text-xs text-muted">AI: {p.reason}</p>}
          </div>
          {!match && <ItemFields compact value={draft} taxonomy={me.taxonomy} provenance={(p.data as any).provenance} onChange={(x) => setDraft((d) => ({ ...d, ...x }))} />}
        </div>
      </div>
      <ItemPicker open={matchPick} onClose={() => setMatchPick(false)} multi={false} title="Which item is it?" onPick={(_, items) => setMatch({ id: items[0].id, name: items[0].name })} />
    </Modal>
  );
}

export function BatchReview() {
  const { id } = useParams();
  const me = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const nav = useNavigate();
  const q = useQuery({
    queryKey: ["batch", id],
    queryFn: () => api<BatchView>(`/batches/${id}`),
    refetchInterval: (query) => (["open", "analyzing", "grouping"].includes(query.state.data?.batch.status || "") ? 2500 : false),
  });
  const [sel, setSel] = useState<string[]>([]);
  const [editing, setEditing] = useState<Proposal | null>(null);
  const [linkPhoto, setLinkPhoto] = useState<string | null>(null);
  const v = q.data;

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["batch", id] });
    qc.invalidateQueries({ queryKey: ["items"] });
    qc.invalidateQueries({ queryKey: ["me"] });
  };
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: any }) => api(path, { method: "POST", body: body ?? {} }),
    onSuccess: refresh,
    onError: (e: any) => toast(e.message, "error"),
  });
  const commit = async (which: string | string[]) => {
    const r = await api<{ committed: number; left: number }>(`/batches/${id}/commit`, { body: Array.isArray(which) ? { proposals: which } : { which } });
    toast(`${r.committed} added to your closet${r.left ? ` · ${r.left} left to review` : ""}`);
    setSel([]);
    refresh();
  };
  const newItemFromPhoto = async (photoId: string, kind: string) => {
    const item = await api<{ id: string }>("/items", { body: { name: "New item" } });
    await api(`/photos/${photoId}/links`, { body: { item_id: item.id, role: kind === "worn" ? "worn" : "shows" } });
    refresh();
    nav(`/item/${item.id}`);
  };

  const pending = useMemo(() => (v?.proposals || []).filter((p) => p.status === "pending"), [v]);
  const decided = useMemo(() => (v?.proposals || []).filter((p) => p.status !== "pending"), [v]);
  const unassigned = (v?.photos || []).filter((p) => !p.assigned && p.status !== "queued" && p.status !== "analyzing");

  if (q.isLoading || !v)
    return (
      <div className="flex justify-center py-24">
        <Spinner />
      </div>
    );
  const b = v.batch;
  const st = STATUS[b.status] || { label: b.status, tone: "neutral" as const };
  const working = ["open", "analyzing", "grouping"].includes(b.status);
  const analyzed = v.photos.filter((p) => p.analysis || p.status === "ready" || p.status === "error").length;
  const confident = pending.filter((p) => (p.confidence || 0) >= (p.match ? 0.8 : 0.7)).length;

  return (
    <div className="mx-auto max-w-[1400px] px-4 pt-4 sm:px-6 lg:px-8 lg:pt-8">
      <Link to="/inbox" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4" /> All imports
      </Link>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-display text-3xl">Import</h1>
            <Badge tone={st.tone}>{st.label}</Badge>
          </div>
          <p className="mt-1 text-sm text-muted">
            {v.photos.length} photos · {ago(b.created_at)}
            {b.note ? ` · “${b.note}”` : ""}
          </p>
          {Object.keys(b.hints || {}).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {Object.entries(b.hints).map(([k, val]) => (
                <Badge key={k}>
                  {cap(k.replace("_", " "))}: {Array.isArray(val) ? val.join(", ") : String(val)}
                </Badge>
              ))}
            </div>
          )}
        </div>
        {me.can_edit && (
          <div className="flex flex-wrap gap-2">
            {sel.length >= 2 && (
              <Button onClick={() => act.mutate({ path: "/proposals/merge", body: { ids: sel } }, { onSuccess: () => setSel([]) })}>
                <Combine className="size-4" /> Same item ({sel.length})
              </Button>
            )}
            {sel.length > 0 && (
              <Button variant="primary" onClick={() => commit(sel)}>
                <Check className="size-4" /> Add {sel.length} selected
              </Button>
            )}
            {sel.length === 0 && confident > 0 && confident < pending.length && <Button onClick={() => commit("confident")}>Add {confident} sure ones</Button>}
            {sel.length === 0 && pending.length > 0 && (
              <Button variant="primary" onClick={() => commit("all")}>
                <Check className="size-4" /> Add all {pending.length}
              </Button>
            )}
            {(b.status === "review" || b.status === "open") && me.vision && (
              <Button variant="ghost" onClick={() => act.mutate({ path: `/batches/${id}/analyze` })} title="Analyse again">
                <RefreshCw className="size-4" />
              </Button>
            )}
            {b.status !== "done" && b.status !== "cancelled" && (
              <Button
                variant="ghost"
                onClick={async () => {
                  if (!confirm("Cancel this import? Items already added stay.")) return;
                  await api(`/batches/${id}`, { method: "DELETE" });
                  refresh();
                }}
                title="Cancel import"
              >
                <Trash2 className="size-4" />
              </Button>
            )}
          </div>
        )}
      </div>

      {working && (
        <Card className="mt-6 p-4">
          <div className="flex items-center gap-3 text-sm">
            <Spinner />
            <span>
              {b.status === "grouping" ? "Matching the same piece across photos and reading tags…" : `Looking at photos — ${analyzed} of ${v.photos.length} done`}
            </span>
          </div>
          <Progress className="mt-3" value={b.status === "grouping" ? 0.95 : v.photos.length ? analyzed / v.photos.length : 0} tone="accent" />
          <p className="mt-2 text-xs text-muted">You can leave this page — the work continues on the server.</p>
        </Card>
      )}

      {pending.length > 0 && (
        <>
          <div className="mt-8 mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-2">Found {pending.length} {pending.length === 1 ? "piece" : "pieces"}</h2>
            <span className="text-xs text-muted">Select two or more to merge them into one item</span>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {pending.map((p) => (
              <ProposalCard
                key={p.id}
                p={p}
                busy={act.isPending}
                selected={sel.includes(p.id)}
                onSelect={() => setSel((s) => (s.includes(p.id) ? s.filter((x) => x !== p.id) : [...s, p.id]))}
                onEdit={() => setEditing(p)}
                onAccept={() => act.mutate({ path: `/proposals/${p.id}/accept` })}
                onReject={() => act.mutate({ path: `/proposals/${p.id}/reject` })}
              />
            ))}
          </div>
        </>
      )}

      {!working && pending.length === 0 && decided.length === 0 && unassigned.length === 0 && (
        <Empty title="No pieces found">The photos are saved in your library. Link them to items from the photo page.</Empty>
      )}

      {unassigned.length > 0 && !working && (
        <>
          <h2 className="mt-10 mb-1 text-sm font-semibold uppercase tracking-wide text-ink-2">Photos without an item ({unassigned.length})</h2>
          <p className="mb-3 text-xs text-muted">Nothing was matched in these. Make an item from one, link it to something you own, or leave it in your library.</p>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-7">
            {unassigned.map((ph) => (
              <div key={ph.id} className="group relative aspect-[3/4] overflow-hidden rounded-xl bg-canvas">
                <img src={ph.image.sm} className="size-full object-cover" alt="" />
                <div className="absolute inset-x-0 top-0 p-1.5">
                  <Badge tone="dark">{cap(ph.analysis?.kind || ph.kind)}</Badge>
                </div>
                {ph.error && <div className="absolute inset-x-0 bottom-0 bg-danger/90 p-1 text-[10px] text-white">{ph.error}</div>}
                {me.can_edit && (
                  <div className="absolute inset-0 hidden flex-col items-center justify-center gap-1.5 bg-ink/50 p-2 group-hover:flex [@media(hover:none)]:top-auto [@media(hover:none)]:flex [@media(hover:none)]:bg-ink/40">
                    <Button size="sm" className="w-full" onClick={() => newItemFromPhoto(ph.id, ph.kind)}>
                      <Plus className="size-3.5" /> New item
                    </Button>
                    <Button size="sm" className="w-full" onClick={() => setLinkPhoto(ph.id)}>
                      <Link2 className="size-3.5" /> Link
                    </Button>
                    <Link to={`/photo/${ph.id}`} className="text-[11px] text-white underline">
                      Open
                    </Link>
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {decided.length > 0 && (
        <>
          <h2 className="mt-10 mb-3 text-sm font-semibold uppercase tracking-wide text-ink-2">Done ({decided.length})</h2>
          <div className="grid grid-cols-3 gap-3 pb-10 sm:grid-cols-4 lg:grid-cols-6">
            {decided.map((p) => (
              <ProposalCard key={p.id} p={p} busy selected={false} onSelect={() => {}} onEdit={() => {}} onAccept={() => {}} onReject={() => {}} />
            ))}
          </div>
        </>
      )}
      <div className="h-10" />
      {editing && <EditProposal p={editing} onClose={() => setEditing(null)} />}
      <ItemPicker
        open={!!linkPhoto}
        onClose={() => setLinkPhoto(null)}
        multi={false}
        title="Which item is in this photo?"
        onPick={async (ids) => {
          const ph = v.photos.find((x) => x.id === linkPhoto);
          await api(`/photos/${linkPhoto}/links`, { body: { item_id: ids[0], role: ph?.kind === "worn" ? "worn" : "shows" } });
          toast("Linked");
          refresh();
        }}
      />
    </div>
  );
}
