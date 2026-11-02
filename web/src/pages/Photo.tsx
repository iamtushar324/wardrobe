import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Link2, Replace, RotateCcw, RotateCw, Sparkles, Trash2, UserRound, X } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Photo, type Studio } from "../api";
import { useMe } from "../App";
import { ItemPicker } from "../components/Pickers";
import { ago, Badge, Button, cap, Card, Empty, Field, Select, Spinner, Textarea, useToast } from "../ui";

const ROLE_LABEL: Record<string, string> = { shows: "Shows it", worn: "I'm wearing it", tag: "Tag", receipt: "Receipt", detail: "Detail", generated: "AI picture" };

export default function PhotoPage() {
  const { id } = useParams();
  const me = useMe();
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useToast();
  const q = useQuery({ queryKey: ["photo", id], queryFn: () => api<Photo>(`/photos/${id}`) });
  const studio = useQuery({ queryKey: ["studio"], queryFn: () => api<Studio>("/studio"), enabled: me.can_edit });
  const [picker, setPicker] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const p = q.data;

  const set = (photo: Photo) => {
    qc.setQueryData(["photo", id], photo);
    qc.invalidateQueries({ queryKey: ["photos"] });
    qc.invalidateQueries({ queryKey: ["items"] });
  };
  const patch = useMutation({ mutationFn: (body: any) => api<Photo>(`/photos/${id}`, { method: "PATCH", body }), onSuccess: set });
  const link = useMutation({
    mutationFn: (itemId: string) => api<Photo>(`/photos/${id}/links`, { body: { item_id: itemId, role: p?.kind === "worn" ? "worn" : "shows" } }),
    onSuccess: (ph) => {
      set(ph);
      toast("Linked");
    },
    onError: (e: any) => toast(e.message, "error"),
  });
  const setRole = async (linkId: string, role: string) => set(await api<Photo>(`/links/${linkId}`, { method: "PATCH", body: { role } }));
  const unlink = async (linkId: string) => {
    await api(`/links/${linkId}`, { method: "DELETE" });
    qc.invalidateQueries({ queryKey: ["photo", id] });
    qc.invalidateQueries({ queryKey: ["items"] });
  };
  const remove = async () => {
    if (!confirm("Delete this photo? Items keep their other photos.")) return;
    await api(`/photos/${id}`, { method: "DELETE" });
    qc.invalidateQueries();
    toast("Photo deleted");
    nav(-1);
  };
  const turn = useMutation({
    mutationFn: (degrees: number) => api<Photo>(`/photos/${id}/rotate`, { body: { degrees } }),
    onSuccess: (ph) => {
      set(ph);
      qc.invalidateQueries({ queryKey: ["item"] });
    },
    onError: (e: any) => toast(e.message, "error"),
  });
  const modelIds = studio.data?.prefs.model_photo_ids || [];
  const isModel = !!p && modelIds.includes(p.id);
  const toggleModel = async () => {
    const next = isModel ? modelIds.filter((x) => x !== p!.id) : [p!.id, ...modelIds].slice(0, 6);
    await api("/studio/prefs", { method: "PATCH", body: { model_photo_ids: next } });
    qc.invalidateQueries({ queryKey: ["studio"] });
    toast(isModel ? "Removed from model photos" : "Studio will use this photo of you");
  };

  if (q.isLoading)
    return (
      <div className="flex justify-center py-24">
        <Spinner />
      </div>
    );
  if (!p) return <Empty title="Photo not found">It may have been deleted.</Empty>;
  const links = p.links || [];

  return (
    <div className="mx-auto max-w-[1400px] px-4 pt-4 sm:px-6 lg:px-8 lg:pt-8">
      <button onClick={() => nav(-1)} className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4" /> Back
      </button>
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="lg:sticky lg:top-6 lg:self-start">
          <div className="relative mx-auto w-fit overflow-hidden rounded-3xl bg-[#ebe7e0]">
            <img src={p.image.lg} alt="" className="max-h-[78vh] w-auto" />
            {me.can_edit && (
              <div className="absolute right-3 top-3 z-10 flex gap-1.5">
                <Button size="icon" variant="secondary" disabled={turn.isPending} onClick={() => turn.mutate(-90)} title="Turn left">
                  <RotateCcw className="size-4" />
                </Button>
                <Button size="icon" variant="secondary" disabled={turn.isPending} onClick={() => turn.mutate(90)} title="Turn right">
                  <RotateCw className="size-4" />
                </Button>
              </div>
            )}
            {links.map(
              (l) =>
                l.bbox && (
                  <div
                    key={l.id}
                    className={`absolute rounded-lg border-2 transition-colors ${hover === l.id ? "border-white bg-white/15" : "border-white/60"}`}
                    style={{ left: `${l.bbox[0] * 100}%`, top: `${l.bbox[1] * 100}%`, width: `${(l.bbox[2] - l.bbox[0]) * 100}%`, height: `${(l.bbox[3] - l.bbox[1]) * 100}%` }}
                  >
                    {hover === l.id && <span className="absolute -top-6 left-0 whitespace-nowrap rounded bg-ink px-1.5 py-0.5 text-[11px] text-paper">{l.item?.name}</span>}
                  </div>
                ),
            )}
          </div>
        </div>
        <div className="space-y-6 pb-10">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={p.ai ? "accent" : "neutral"}>{p.ai ? "AI picture" : cap(p.kind)}</Badge>
              {p.ai && p.template && <Badge>{studio.data?.templates.find((t) => t.id === p.template)?.name || p.template}</Badge>}
              {isModel && <Badge tone="dark">Model photo</Badge>}
            </div>
            <h1 className="font-display mt-3 text-3xl">{p.ai ? "AI picture" : p.filename || "Photo"}</h1>
            <p className="mt-1 text-xs text-muted">
              Added {ago(p.created_at)}
              {p.created_by?.startsWith("agent:") ? ` by ${p.created_by.split(":")[1]}` : ""} · {p.width}×{p.height}
            </p>
            {p.error && <p className="mt-2 text-sm text-danger">{p.error}</p>}
          </div>

          <Card className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="text-[12px] font-semibold uppercase tracking-wide text-ink-2">In this photo</div>
              {me.can_edit && (
                <Button size="sm" onClick={() => setPicker(true)}>
                  <Link2 className="size-3.5" /> Link item
                </Button>
              )}
            </div>
            {links.length === 0 ? (
              <p className="text-sm text-muted">Not linked to any item yet.</p>
            ) : (
              <ul className="space-y-2">
                {links.map((l) => (
                  <li key={l.id} className="flex items-center gap-3" onMouseEnter={() => setHover(l.id)} onMouseLeave={() => setHover(null)}>
                    <Link to={`/item/${l.item_id}`} className="size-12 shrink-0 overflow-hidden rounded-xl bg-canvas">
                      {(l.cutout || l.crop) && <img src={(l.cutout || l.crop)!.sm} className="size-full object-contain p-1" alt="" />}
                    </Link>
                    <div className="min-w-0 flex-1">
                      <Link to={`/item/${l.item_id}`} className="block truncate text-sm font-medium hover:underline">
                        {l.item?.name || "Item"}
                      </Link>
                      {me.can_edit ? (
                        <select
                          value={l.role}
                          onChange={(e) => setRole(l.id, e.target.value)}
                          className="mt-0.5 bg-transparent text-xs text-muted outline-none"
                        >
                          {Object.entries(ROLE_LABEL).map(([v, label]) => (
                            <option key={v} value={v}>
                              {label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <div className="text-xs text-muted">{ROLE_LABEL[l.role] || l.role}</div>
                      )}
                    </div>
                    {l.confidence !== null && !l.confirmed && <Badge>AI {Math.round((l.confidence || 0) * 100)}%</Badge>}
                    {me.can_edit && (
                      <Button size="icon" variant="ghost" onClick={() => unlink(l.id)} aria-label="Unlink">
                        <X className="size-4" />
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {me.can_edit && (
            <Card className="space-y-4 p-4">
              <Field label="What kind of photo">
                <Select
                  value={p.kind}
                  onChange={(kind) => patch.mutate({ kind, ...(kind === "worn" ? { people: [me.user.id] } : {}) })}
                  options={me.taxonomy.photo_kinds.map((k) => ({ value: k, label: cap(k) }))}
                />
              </Field>
              <Field label="Note">
                <Textarea rows={2} value={note ?? p.note ?? ""} onChange={(e) => setNote(e.target.value)} onBlur={() => note !== null && note !== (p.note || "") && patch.mutate({ note })} />
              </Field>
              <div className="flex flex-wrap gap-2">
                {p.kind === "worn" && (
                  <Link to={`/tryon?photo=${p.id}`}>
                    <Button variant="primary">
                      <Replace className="size-4" /> Try on other clothes
                    </Button>
                  </Link>
                )}
                {p.kind === "worn" && !p.ai && (
                  <Button variant={isModel ? "soft" : "secondary"} onClick={toggleModel}>
                    <UserRound className="size-4" /> {isModel ? "Stop using as model photo" : "Use as my model photo"}
                  </Button>
                )}
                {p.ai && p.gen_job_id && (
                  <Link to="/studio">
                    <Button>
                      <Sparkles className="size-4" /> Open in Studio
                    </Button>
                  </Link>
                )}
                <Button variant="ghost" onClick={remove}>
                  <Trash2 className="size-4" /> Delete photo
                </Button>
              </div>
            </Card>
          )}
        </div>
      </div>
      <ItemPicker open={picker} onClose={() => setPicker(false)} multi={false} title="Which item is in this photo?" exclude={links.map((l) => l.item_id)} onPick={(ids) => link.mutate(ids[0])} />
    </div>
  );
}
