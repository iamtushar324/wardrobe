import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight, Ban, CircleAlert, ImagePlus, Images, Loader2, Plus, Replace, RotateCcw, Scissors, Shirt, Sparkles, X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type Img, type Item, type Job, type Photo, type Studio } from "../api";
import { useMe } from "../App";
import { ItemPicker, PhotoPicker } from "../components/Pickers";
import { ago, Badge, Button, Card, Chip, cx, dur, Empty, Input, Segmented, Spinner, Textarea, Toggle, useToast } from "../ui";

type Background = "keep" | "tidy" | "studio" | "blur" | "scene";
type Crop = "original" | "card" | "square" | "tight";

type Options = {
  background: Background;
  scene: string;
  keep_rest: boolean;
  light: boolean;
  smooth: boolean;
  crop: Crop;
  transparent: boolean;
  cover: boolean;
  variants: number;
  extra: string;
};

const DEFAULTS: Options = {
  background: "keep", scene: "", keep_rest: true, light: false, smooth: false,
  crop: "original", transparent: false, cover: false, variants: 1, extra: "",
};

// One-tap starting points; every switch below stays editable afterwards.
const PRESETS: { id: string; label: string; hint: string; set: Partial<Options> }[] = [
  { id: "swap", label: "Just swap the clothes", hint: "Same photo, new outfit", set: { background: "keep", crop: "original", transparent: false, light: false, smooth: false } },
  { id: "tidy", label: "Swap + tidy the room", hint: "Removes clutter behind you", set: { background: "tidy", crop: "original", transparent: false, light: true } },
  { id: "closet", label: "Closet-ready", hint: "White studio, 3:4 card", set: { background: "studio", crop: "card", transparent: false, light: true, smooth: true } },
  { id: "cutout", label: "Cut-out", hint: "Transparent background", set: { background: "studio", crop: "tight", transparent: true, smooth: true } },
];

const BACKGROUNDS: { value: Background; label: string }[] = [
  { value: "keep", label: "Keep as is" },
  { value: "tidy", label: "Tidy up" },
  { value: "studio", label: "Studio white" },
  { value: "blur", label: "Soft blur" },
  { value: "scene", label: "New scene" },
];

const CROPS: { value: Crop; label: string }[] = [
  { value: "original", label: "Original" },
  { value: "card", label: "Closet card 3:4" },
  { value: "square", label: "Square" },
  { value: "tight", label: "Tight on me" },
];

const checker = {
  backgroundImage: "conic-gradient(#ece8e1 25%, #fff 0 50%, #ece8e1 0 75%, #fff 0)",
  backgroundSize: "18px 18px",
};

function Step({ n, title, children, aside }: { n: number; title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section>
      <div className="mb-3 flex items-center gap-2.5">
        <span className="grid size-6 place-items-center rounded-full bg-ink text-[12px] font-semibold text-paper">{n}</span>
        <h2 className="font-medium">{title}</h2>
        <div className="ml-auto">{aside}</div>
      </div>
      {children}
    </section>
  );
}

function ResultCard({ j, onRetry, onCancel, canEdit }: { j: Job; onRetry: () => void; onCancel: () => void; canEdit: boolean }) {
  const [before, setBefore] = useState(false);
  const o = (j.options || {}) as Partial<Options>;
  const shown: Img | null | undefined = before || !j.result ? j.base : j.result;
  const transparent = !!o.transparent && !before && !!j.result;
  const label =
    j.status === "done" ? null
      : j.status === "running" ? (j.finishing ? "Finishing touches" : `Making · ${dur(j.elapsed_s)}`)
        : j.status === "queued" ? `#${j.position ?? "–"} in queue`
          : j.status === "failed" ? "Failed" : "Cancelled";
  return (
    <Card className="overflow-hidden">
      <div
        className={cx("relative aspect-[3/4] select-none bg-canvas", j.result && "cursor-pointer")}
        style={transparent ? checker : undefined}
        onPointerDown={() => j.result && setBefore(true)}
        onPointerUp={() => setBefore(false)}
        onPointerLeave={() => setBefore(false)}
      >
        {shown && <img src={shown.md} draggable={false} className={cx("size-full", transparent ? "object-contain" : "object-cover", !j.result && "opacity-60")} alt="" />}
        {label && (
          <div className="absolute inset-0 grid place-items-center">
            <Badge tone={j.status === "failed" ? "danger" : "dark"} className="text-xs">
              {(j.status === "running" || j.status === "queued") && <Loader2 className={cx("size-3", j.status === "running" && "animate-spin")} />}
              {label}
            </Badge>
          </div>
        )}
        {j.result && (
          <span className="absolute left-2 top-2">
            <Badge tone="dark">{before ? "Before" : "After"}</Badge>
          </span>
        )}
        {j.result && j.base && !before && (
          <img src={j.base.sm} className="absolute bottom-2 right-2 size-14 rounded-lg border-2 border-white object-cover shadow" alt="Before" />
        )}
      </div>
      <div className="space-y-1.5 p-3">
        <div className="flex items-center gap-1.5 text-sm">
          <span className="min-w-0 flex-1 truncate font-medium">{(j.items || []).map((i) => i.name).join(" + ") || "Try on"}</span>
          {canEdit && (j.status === "failed" || j.status === "cancelled") && (
            <Button size="icon" variant="ghost" onClick={onRetry} title="Try again">
              <RotateCcw className="size-4" />
            </Button>
          )}
          {canEdit && j.status === "queued" && (
            <Button size="icon" variant="ghost" onClick={onCancel} title="Cancel">
              <X className="size-4" />
            </Button>
          )}
        </div>
        <div className="flex flex-wrap gap-1 text-xs text-muted">
          {o.background && o.background !== "keep" && <Badge>{BACKGROUNDS.find((b) => b.value === o.background)?.label}</Badge>}
          {o.crop && o.crop !== "original" && <Badge>{CROPS.find((c) => c.value === o.crop)?.label}</Badge>}
          {o.transparent && <Badge>Cut-out</Badge>}
          {o.cover && <Badge tone="accent">Main picture</Badge>}
          <span className="self-center">{ago(j.finished_at || j.created_at)}</span>
        </div>
        {j.error && <div className="line-clamp-2 text-xs text-danger">{j.error}</div>}
        {j.result && (
          <div className="flex items-center justify-between pt-1 text-xs">
            <span className="text-muted">Hold the picture to compare</span>
            <Link to={`/photo/${j.result_photo_id}`} className="inline-flex items-center gap-1 font-medium text-ink hover:underline">
              Open <ArrowRight className="size-3" />
            </Link>
          </div>
        )}
      </div>
    </Card>
  );
}

export default function TryOn() {
  const me = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const studio = useQuery({
    queryKey: ["studio"],
    queryFn: () => api<Studio>("/studio"),
    refetchInterval: (query) => ((query.state.data?.counts.queued || 0) + (query.state.data?.counts.running || 0) > 0 ? 4000 : 15000),
  });
  const [base, setBase] = useState<{ id: string; image: Img } | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [o, setO] = useState<Options>(DEFAULTS);
  const [preset, setPreset] = useState("swap");
  const [pickItems, setPickItems] = useState(false);
  const [pickPhoto, setPickPhoto] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const set = (p: Partial<Options>) => {
    setO((v) => ({ ...v, ...p }));
    setPreset("");
  };

  // ?photo=<id>&items=a,b from the photo and item pages
  useEffect(() => {
    const pid = params.get("photo");
    const iids = (params.get("items") || "").split(",").filter(Boolean);
    if (pid) api<Photo>(`/photos/${pid}`).then((p) => setBase({ id: p.id, image: p.image })).catch(() => toast("That photo is gone", "error"));
    if (iids.length)
      Promise.all(iids.map((i) => api<Item>(`/items/${i}`).catch(() => null))).then((r) =>
        setItems((cur) => [...cur, ...(r.filter(Boolean) as Item[]).filter((x) => !cur.some((c) => c.id === x.id))].slice(0, 6)),
      );
    if (pid || iids.length) setParams({}, { replace: true });
  }, []);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append("files", files[0]);
      form.append("kind", "worn");
      const r = await api<{ results: { photo_id?: string; error?: string; duplicate?: boolean }[] }>("/photos", { form });
      const res = r.results[0];
      if (!res?.photo_id) throw new Error(res?.error || "Upload failed");
      const p = await api<Photo>(`/photos/${res.photo_id}`);
      setBase({ id: p.id, image: p.image });
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const run = useMutation({
    mutationFn: () => api<{ jobs: Job[] }>("/studio/tryon", { body: { photo_id: base!.id, item_ids: items.map((i) => i.id), options: o } }),
    onSuccess: (r) => {
      toast(`${r.jobs.length === 1 ? "Try-on" : `${r.jobs.length} versions`} queued — they show up below`);
      qc.invalidateQueries({ queryKey: ["studio"] });
      qc.invalidateQueries({ queryKey: ["me"] });
      setTimeout(() => document.getElementById("results")?.scrollIntoView({ behavior: "smooth" }), 150);
    },
    onError: (e: any) => toast(e.message, "error"),
  });
  const post = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: any }) => api(path, { method: "POST", body: body ?? {} }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["studio"] }),
    onError: (e: any) => toast(e.message, "error"),
  });

  if (!me.can_edit) return <Empty icon={<Replace className="size-6" />} title="Try on needs edit access">You're viewing someone else's wardrobe.</Empty>;
  const s = studio.data;
  const jobs = (s?.jobs || []).filter((j) => j.template === "tryon");
  const multi = items.length > 1;

  return (
    <div className="mx-auto max-w-[1400px] px-4 pt-5 sm:px-6 lg:px-8 lg:pt-8">
      <div className="mb-6">
        <h1 className="font-display text-3xl sm:text-4xl">Try on</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Pick a photo of you and the clothes to put on. The AI only changes the clothes you choose; your face, pose, the
          light and the rest of the picture stay as close to the original as it can.
        </p>
      </div>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        {/* 1. photo */}
        <div className="lg:sticky lg:top-6 lg:self-start">
          <Step
            n={1}
            title="Your photo"
            aside={
              base && (
                <Button size="sm" variant="ghost" onClick={() => setBase(null)}>
                  Change
                </Button>
              )
            }
          >
            {base ? (
              <div className="relative overflow-hidden rounded-3xl bg-[#ebe7e0]">
                <img src={base.image.lg} className="max-h-[70vh] w-full object-contain" alt="Your photo" />
              </div>
            ) : (
              <div className="rounded-3xl border border-dashed border-[#cfc9bf] p-6">
                <div className="flex flex-wrap justify-center gap-2">
                  <Button variant="primary" loading={uploading} onClick={() => fileRef.current?.click()}>
                    <ImagePlus className="size-4" /> Upload a photo
                  </Button>
                  <Button onClick={() => setPickPhoto(true)}>
                    <Images className="size-4" /> From my photos
                  </Button>
                </div>
                {s && s.model_photos.length > 0 && (
                  <>
                    <div className="mb-2 mt-6 text-center text-[12px] font-semibold uppercase tracking-wide text-muted">or one of your model photos</div>
                    <div className="flex flex-wrap justify-center gap-2">
                      {s.model_photos.map((m) => (
                        <button key={m.id} onClick={() => setBase(m)} className="size-24 overflow-hidden rounded-xl bg-canvas ring-ink hover:ring-2">
                          <img src={m.image.sm} className="size-full object-cover" alt="" />
                        </button>
                      ))}
                    </div>
                  </>
                )}
                <p className="mt-5 text-center text-xs text-muted">Works best with a clear, well-lit photo where the clothes you're replacing are visible.</p>
              </div>
            )}
            <input ref={fileRef} type="file" accept="image/*,.heic,.heif" className="hidden" onChange={(e) => upload(e.target.files)} />
          </Step>
        </div>

        <div className="space-y-8">
          {/* 2. clothes */}
          <Step n={2} title="What to wear" aside={<span className="text-xs text-muted">{items.length}/6</span>}>
            <div className="flex flex-wrap gap-2.5">
              {items.map((it) => (
                <div key={it.id} className="relative w-24">
                  <div className="aspect-square overflow-hidden rounded-xl bg-canvas">
                    {it.cover && <img src={it.cover.sm} className={cx("size-full", it.cover.cutout ? "object-contain p-1.5" : "object-cover")} alt="" />}
                  </div>
                  <div className="mt-1 truncate text-xs">{it.name}</div>
                  <button
                    onClick={() => setItems((v) => v.filter((x) => x.id !== it.id))}
                    className="absolute right-1 top-1 rounded-full bg-white/90 p-0.5 shadow"
                    aria-label={`Remove ${it.name}`}
                  >
                    <X className="size-3.5" />
                  </button>
                </div>
              ))}
              {items.length < 6 && (
                <button onClick={() => setPickItems(true)} className="grid aspect-square w-24 place-items-center rounded-xl border border-dashed border-[#cfc9bf] text-muted hover:bg-canvas">
                  <span className="flex flex-col items-center gap-1 text-xs">
                    <Plus className="size-5" /> {items.length ? "Add more" : "Choose"}
                  </span>
                </button>
              )}
            </div>
            {multi && <p className="mt-2 text-xs text-muted">All of these go on together as one outfit.</p>}
          </Step>

          {/* 3. look */}
          <Step n={3} title="How it should look">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {PRESETS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => {
                    setO((v) => ({ ...v, ...p.set }));
                    setPreset(p.id);
                  }}
                  className={cx(
                    "rounded-2xl border p-3 text-left transition-colors",
                    preset === p.id ? "border-ink bg-ink text-paper" : "border-line bg-white hover:border-[#cfc9bf]",
                  )}
                >
                  <div className="text-sm font-medium leading-tight">{p.label}</div>
                  <div className={cx("mt-1 text-xs", preset === p.id ? "text-[#d9d4cb]" : "text-muted")}>{p.hint}</div>
                </button>
              ))}
            </div>

            <div className="mt-5 space-y-5 rounded-2xl bg-canvas p-4">
              <div>
                <div className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted">Background</div>
                <div className="flex flex-wrap gap-1.5">
                  {BACKGROUNDS.map((b) => (
                    <Chip key={b.value} active={o.background === b.value} onClick={() => set({ background: b.value })}>
                      {b.label}
                    </Chip>
                  ))}
                </div>
                {o.background === "scene" && (
                  <Input className="mt-2" value={o.scene} onChange={(e) => set({ scene: e.target.value })} placeholder="e.g. a café in Bandra on a sunny morning" />
                )}
                {o.background === "tidy" && <p className="mt-1.5 text-xs text-muted">Keeps your room, removes the mess (clothes on the bed, bags, wires).</p>}
              </div>

              <div>
                <div className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted">For the website</div>
                <Segmented<Crop> value={o.crop} onChange={(v) => set({ crop: v })} options={CROPS} className="flex-wrap" />
                <p className="mt-1.5 text-xs text-muted">
                  {o.crop === "original"
                    ? "Keeps the whole picture."
                    : o.crop === "card"
                      ? "Crops around you (found by AI) to the 3:4 shape the closet uses, a little more room above the head."
                      : o.crop === "square"
                        ? "A square crop centred on you."
                        : "Crops close around you."}
                </p>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <Toggle checked={o.keep_rest} onChange={(v) => set({ keep_rest: v })} label="Keep the rest of my outfit" />
                <Toggle checked={o.light} onChange={(v) => set({ light: v })} label="Even out the light" />
                <Toggle checked={o.smooth} onChange={(v) => set({ smooth: v })} label="Smooth out creases" />
                <Toggle
                  checked={o.transparent}
                  onChange={(v) => set({ transparent: v })}
                  label={
                    <span className="inline-flex items-center gap-1.5">
                      <Scissors className="size-3.5" /> Cut me out (transparent)
                    </span>
                  }
                />
                <Toggle
                  checked={o.cover}
                  onChange={(v) => set({ cover: v })}
                  label={multi ? "Use as each item's main picture" : "Use as the item's main picture"}
                />
              </div>

              <div>
                <div className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted">Anything else? (optional)</div>
                <Textarea
                  rows={2}
                  value={o.extra}
                  onChange={(e) => set({ extra: e.target.value })}
                  placeholder="e.g. remove the clothes on the bed behind me, tuck the shirt in, roll up the sleeves"
                />
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <span className="text-[12px] font-semibold uppercase tracking-wide text-muted">Versions</span>
                <Segmented<string>
                  value={String(o.variants)}
                  onChange={(v) => set({ variants: Number(v) })}
                  options={[{ value: "1", label: "1" }, { value: "2", label: "2" }, { value: "3", label: "3" }]}
                />
                <span className="text-xs text-muted">Each version is one AI picture.</span>
              </div>
            </div>
          </Step>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              size="lg"
              disabled={!base || !items.length || (o.background === "scene" && !o.scene.trim())}
              loading={run.isPending}
              onClick={() => run.mutate()}
            >
              <Sparkles className="size-4" /> Try it on{o.variants > 1 ? ` · ${o.variants} versions` : ""}
            </Button>
            {!base ? (
              <span className="text-sm text-muted">Choose your photo first.</span>
            ) : !items.length ? (
              <span className="text-sm text-muted">Choose what to wear.</span>
            ) : s && !s.available ? (
              <span className="inline-flex items-center gap-1.5 text-sm text-warn">
                <CircleAlert className="size-4" /> Will wait: {s.reason}
              </span>
            ) : (
              <span className="text-sm text-muted">Usually ready in a minute or two.</span>
            )}
          </div>
        </div>
      </div>

      {/* results */}
      <section id="results" className="mt-12 pb-10">
        <div className="mb-4 flex items-center gap-2">
          <Shirt className="size-5" />
          <h2 className="font-display text-2xl">Your try-ons</h2>
          {jobs.some((j) => j.status === "queued") && (
            <Button
              size="sm"
              variant="ghost"
              className="ml-auto"
              onClick={() => post.mutate({ path: "/studio/cancel", body: { ids: jobs.filter((j) => j.status === "queued").map((j) => j.id) } })}
            >
              <Ban className="size-3.5" /> Cancel waiting
            </Button>
          )}
        </div>
        {!s ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : jobs.length ? (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
            {jobs.map((j) => (
              <ResultCard
                key={j.id}
                j={j}
                canEdit={me.can_edit}
                onRetry={() => post.mutate({ path: `/studio/jobs/${j.id}/retry` })}
                onCancel={() => post.mutate({ path: "/studio/cancel", body: { ids: [j.id] } })}
              />
            ))}
          </div>
        ) : (
          <p className="rounded-2xl bg-canvas p-6 text-center text-sm text-muted">Nothing tried on yet. Your results will appear here, with the before picture to compare.</p>
        )}
      </section>

      <ItemPicker
        open={pickItems}
        onClose={() => setPickItems(false)}
        title="What do you want to wear?"
        max={6 - items.length}
        exclude={items.map((i) => i.id)}
        onPick={(_ids, picked) => setItems((v) => [...v, ...picked].slice(0, 6))}
      />
      <PhotoPicker open={pickPhoto} onClose={() => setPickPhoto(false)} title="Choose a photo of you" query={{ kind: "worn" }} onPick={(p) => setBase({ id: p.id, image: p.image })} />
    </div>
  );
}
