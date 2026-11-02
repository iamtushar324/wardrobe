import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, ExternalLink, Heart, ImagePlus, Scissors, Sparkles, Trash2, User } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, uploadForm, type Item, type ItemPhoto } from "../api";
import { useMe } from "../App";
import { diff, ItemFields, type Draft } from "../components/ItemForm";
import { GenerateDialog } from "../components/Pickers";
import { ago, Badge, Button, cap, cx, Empty, money, Segmented, Select, Spinner, Swatch, useToast } from "../ui";

type Tab = "all" | "product" | "worn" | "ai" | "docs";

function tabOf(p: ItemPhoto): Tab {
  if (p.role === "generated" || p.photo.ai) return "ai";
  if (p.role === "worn") return "worn";
  if (p.role === "tag" || p.role === "receipt") return "docs";
  return "product";
}

export default function ItemPage() {
  const { id } = useParams();
  const me = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["item", id], queryFn: () => api<Item>(`/items/${id}`) });
  const item = q.data;
  const [draft, setDraft] = useState<Draft>({});
  const [tab, setTab] = useState<Tab>("all");
  const [sel, setSel] = useState<string | null>(null);
  const [cutoutView, setCutoutView] = useState(true);
  const [gen, setGen] = useState(false);
  const [role, setRole] = useState("shows");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (item) setDraft({});
  }, [item?.updated_at]);

  const merged = useMemo(() => ({ ...(item || {}), ...draft }) as Draft, [item, draft]);
  const changes = item ? diff(item, merged as any) : {};
  const dirty = Object.keys(changes).length > 0;

  const save = useMutation({
    mutationFn: () => api<Item>(`/items/${id}`, { method: "PATCH", body: changes }),
    onSuccess: (it) => {
      qc.setQueryData(["item", id], it);
      qc.invalidateQueries({ queryKey: ["items"] });
      setDraft({});
      toast("Saved");
    },
    onError: (e: any) => toast(e.message, "error"),
  });
  const patch = async (body: Partial<Item>) => {
    const it = await api<Item>(`/items/${id}`, { method: "PATCH", body });
    qc.setQueryData(["item", id], it);
    qc.invalidateQueries({ queryKey: ["items"] });
  };
  const wear = useMutation({
    mutationFn: () => api<Item>(`/items/${id}/wear`, { method: "POST" }),
    onSuccess: (it) => {
      qc.setQueryData(["item", id], it);
      toast("Marked as worn today");
    },
  });
  const remove = async () => {
    if (!confirm(`Delete “${item?.name}”? Its photos stay in your library.`)) return;
    await api(`/items/${id}`, { method: "DELETE" });
    qc.invalidateQueries();
    toast("Deleted");
    nav("/");
  };
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f));
    form.append("role", role);
    try {
      const r = await uploadForm<{ item: Item }>(`/api/v1/items/${id}/photos`, form);
      qc.setQueryData(["item", id], r.item);
      toast(`${files.length} photo${files.length === 1 ? "" : "s"} added`);
      setTimeout(() => qc.invalidateQueries({ queryKey: ["item", id] }), 6000); // cutouts arrive in the background
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  if (q.isLoading)
    return (
      <div className="flex justify-center py-24">
        <Spinner />
      </div>
    );
  if (!item) return <Empty title="Item not found">It may have been deleted.</Empty>;

  const photos = item.photos || [];
  const shown = photos.filter((p) => tab === "all" || tabOf(p) === tab);
  const current = photos.find((p) => p.link_id === sel) || shown[0] || null;
  const mainImg = current ? (cutoutView && current.cutout ? current.cutout : current.photo.image) : item.cover;
  const counts = { all: photos.length, product: 0, worn: 0, ai: 0, docs: 0 } as Record<Tab, number>;
  photos.forEach((p) => counts[tabOf(p)]++);

  return (
    <div className="mx-auto max-w-[1400px] px-4 pt-4 sm:px-6 lg:px-8 lg:pt-8">
      <button onClick={() => (history.length > 1 ? nav(-1) : nav("/"))} className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4" /> Back
      </button>
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        {/* gallery */}
        <div className="lg:sticky lg:top-6 lg:self-start">
          <div className={cx("relative aspect-[4/5] overflow-hidden rounded-3xl", current?.cutout && cutoutView ? "bg-canvas" : "bg-[#ebe7e0]")}>
            {mainImg ? (
              <img src={mainImg.lg} alt={item.name} className={cx("size-full", current?.cutout && cutoutView ? "object-contain p-[7%]" : "object-contain")} />
            ) : (
              <div className="grid size-full place-items-center text-sm text-muted">No photo yet</div>
            )}
            <div className="absolute left-3 top-3 flex gap-1.5">
              {current && <Badge tone="dark">{current.photo.ai ? "AI picture" : cap(current.role === "shows" ? "photo" : current.role)}</Badge>}
            </div>
            <div className="absolute right-3 top-3 flex gap-1.5">
              {current?.cutout && (
                <Button size="sm" variant="secondary" onClick={() => setCutoutView(!cutoutView)}>
                  <Scissors className="size-3.5" /> {cutoutView ? "Original" : "Cut out"}
                </Button>
              )}
              {current && (
                <Link to={`/photo/${current.photo.id}`}>
                  <Button size="sm" variant="secondary">
                    <ExternalLink className="size-3.5" />
                  </Button>
                </Link>
              )}
            </div>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Segmented<Tab>
              value={tab}
              onChange={(t) => {
                setTab(t);
                setSel(null);
              }}
              options={(
                [
                  ["all", "All"],
                  ["product", "Item"],
                  ["worn", "On me"],
                  ["ai", "AI"],
                  ["docs", "Tags"],
                ] as [Tab, string][]
              )
                .filter(([k]) => k === "all" || counts[k])
                .map(([k, l]) => ({ value: k, label: `${l} ${counts[k]}` }))}
            />
          </div>
          <div className="no-scrollbar mt-3 flex gap-2 overflow-x-auto pb-1">
            {shown.map((p) => (
              <button
                key={p.link_id}
                onClick={() => setSel(p.link_id)}
                className={cx("relative size-20 shrink-0 overflow-hidden rounded-xl bg-canvas", current?.link_id === p.link_id && "ring-2 ring-ink ring-offset-2")}
              >
                <img src={(p.cutout || p.crop || p.photo.image).sm} className={cx("size-full", p.cutout ? "object-contain p-1.5" : "object-cover")} alt="" />
                {p.photo.ai && <Sparkles className="absolute right-1 top-1 size-3.5 text-white drop-shadow" />}
                {p.role === "worn" && !p.photo.ai && <User className="absolute right-1 top-1 size-3.5 text-white drop-shadow" />}
              </button>
            ))}
            {me.can_edit && (
              <div className="flex shrink-0 flex-col gap-1.5">
                <button onClick={() => fileRef.current?.click()} className="grid size-20 place-items-center rounded-xl border border-dashed border-[#cfc9bf] text-muted hover:bg-canvas">
                  <ImagePlus className="size-5" />
                </button>
              </div>
            )}
          </div>
          {me.can_edit && (
            <div className="mt-2 flex items-center gap-2 text-xs text-muted">
              Add as
              <Select
                className="w-36"
                value={role}
                onChange={setRole}
                options={[
                  { value: "shows", label: "Item photo" },
                  { value: "worn", label: "Me wearing it" },
                  { value: "tag", label: "Tag / label" },
                  { value: "receipt", label: "Receipt" },
                  { value: "detail", label: "Detail" },
                ]}
              />
              <input ref={fileRef} type="file" accept="image/*,.heic,.heif" multiple className="hidden" onChange={(e) => upload(e.target.files)} />
            </div>
          )}
        </div>

        {/* details */}
        <div className="pb-10">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-sm text-muted">{[item.brand, cap(item.subcategory || item.category)].filter(Boolean).join(" · ")}</div>
              <h1 className="font-display mt-1 text-3xl leading-tight sm:text-4xl">{item.name}</h1>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {item.colors.map((c) => (
                  <span key={c.name} className="inline-flex items-center gap-1.5 rounded-full bg-canvas py-1 pl-1 pr-2.5 text-xs">
                    <Swatch hex={c.hex} size={14} /> {cap(c.name)}
                  </span>
                ))}
                {item.price !== null && <Badge>{money(item.price, item.currency)}</Badge>}
                {item.original_price !== null && item.original_price !== item.price && (
                  <Badge>
                    MRP <s className="opacity-70">{money(item.original_price, item.currency)}</s>
                  </Badge>
                )}
              </div>
            </div>
            {me.can_edit && (
              <Button variant="ghost" size="icon" onClick={() => patch({ favorite: !item.favorite })} aria-label="Favourite">
                <Heart className={cx("size-5", item.favorite && "fill-[#d64545] text-[#d64545]")} />
              </Button>
            )}
          </div>
          {me.can_edit && (
            <div className="mt-5 flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => setGen(true)}>
                <Sparkles className="size-4" /> AI pictures
              </Button>
              <Button onClick={() => wear.mutate()} loading={wear.isPending}>
                <Check className="size-4" /> Wore it today
              </Button>
              <Button variant="ghost" onClick={remove}>
                <Trash2 className="size-4" />
              </Button>
            </div>
          )}
          <p className="mt-3 text-xs text-muted">
            Worn {item.wear_count} {item.wear_count === 1 ? "time" : "times"}
            {item.last_worn_at ? `, last ${ago(item.last_worn_at)}` : ""} · added {ago(item.created_at)}
            {item.created_by?.startsWith("agent:") ? ` by ${item.created_by.split(":")[1]}` : ""}
          </p>

          <div className="mt-8">
            <fieldset disabled={!me.can_edit}>
              <ItemFields value={merged} taxonomy={me.taxonomy} provenance={item.provenance} onChange={(p) => setDraft((d) => ({ ...d, ...p }))} />
            </fieldset>
          </div>
        </div>
      </div>
      {dirty && (
        <div className="fixed inset-x-0 bottom-20 z-30 flex justify-center px-4 lg:bottom-6 lg:pl-60">
          <div className="fade-in flex items-center gap-3 rounded-full bg-ink py-2 pl-5 pr-2 text-sm text-paper shadow-xl">
            Unsaved changes
            <Button size="sm" variant="ghost" className="text-[#cfc9bf] hover:bg-white/10" onClick={() => setDraft({})}>
              Discard
            </Button>
            <Button size="sm" className="bg-paper text-ink" loading={save.isPending} onClick={() => save.mutate()}>
              Save
            </Button>
          </div>
        </div>
      )}
      <GenerateDialog open={gen} onClose={() => setGen(false)} itemIds={[item.id]} />
    </div>
  );
}
