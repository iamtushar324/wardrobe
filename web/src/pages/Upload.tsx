import { useQueryClient } from "@tanstack/react-query";
import { FolderOpen, ImagePlus, Info, Upload as UploadIcon, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, uploadForm, type Batch } from "../api";
import { useMe } from "../App";
import { Button, cap, Card, Chip, cx, Field, Input, Progress, Segmented, Textarea, useToast } from "../ui";

const IMAGE_RE = /\.(jpe?g|png|heic|heif|webp|avif|gif)$/i;
const CHUNK = 6; // files per request
const MAX_FILES = 500;

type Picked = { file: File; path: string; url: string };

async function walk(entry: any, prefix = ""): Promise<{ file: File; path: string }[]> {
  if (entry.isFile) {
    const file: File = await new Promise((res, rej) => entry.file(res, rej));
    return [{ file, path: prefix + file.name }];
  }
  if (entry.isDirectory) {
    const reader = entry.createReader();
    const out: { file: File; path: string }[] = [];
    // readEntries returns at most ~100 at a time
    for (;;) {
      const batch: any[] = await new Promise((res, rej) => reader.readEntries(res, rej));
      if (!batch.length) break;
      for (const e of batch) out.push(...(await walk(e, prefix + entry.name + "/")));
    }
    return out;
  }
  return [];
}

export default function Upload() {
  const me = useMe();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [files, setFiles] = useState<Picked[]>([]);
  const [drag, setDrag] = useState(false);
  const [note, setNote] = useState("");
  const [hints, setHints] = useState<Record<string, any>>({});
  const [showHints, setShowHints] = useState(false);
  const [mode, setMode] = useState<"review" | "confident">("review");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const dirRef = useRef<HTMLInputElement>(null);

  useEffect(() => () => files.forEach((f) => URL.revokeObjectURL(f.url)), []);
  useEffect(() => {
    dirRef.current?.setAttribute("webkitdirectory", "");
    dirRef.current?.setAttribute("directory", "");
  }, []);

  const add = (list: { file: File; path: string }[]) => {
    setFiles((cur) => {
      const seen = new Set(cur.map((c) => c.path + c.file.size));
      const fresh = list
        .filter((x) => IMAGE_RE.test(x.file.name) || x.file.type.startsWith("image/"))
        .filter((x) => !seen.has(x.path + x.file.size))
        .map((x) => ({ ...x, url: URL.createObjectURL(x.file) }));
      const next = [...cur, ...fresh];
      if (next.length > MAX_FILES) toast(`Up to ${MAX_FILES} photos at a time — the rest were left out`, "error");
      return next.slice(0, MAX_FILES);
    });
  };
  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setDrag(false);
    const items = Array.from(e.dataTransfer.items || []);
    const entries = items.map((i) => (i as any).webkitGetAsEntry?.()).filter(Boolean);
    if (entries.length) {
      const all = (await Promise.all(entries.map((en) => walk(en)))).flat();
      add(all);
    } else add(Array.from(e.dataTransfer.files).map((f) => ({ file: f, path: f.name })));
  };
  const fromInput = (list: FileList | null) => list && add(Array.from(list).map((f) => ({ file: f, path: (f as any).webkitRelativePath || f.name })));

  const folders = useMemo(() => {
    const m = new Map<string, number>();
    files.forEach((f) => {
      const d = f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : "";
      m.set(d, (m.get(d) || 0) + 1);
    });
    return m;
  }, [files]);
  const size = files.reduce((s, f) => s + f.file.size, 0);

  const start = async () => {
    setBusy(true);
    setProgress(0);
    try {
      setStage("Creating import…");
      const cleanHints = Object.fromEntries(Object.entries(hints).filter(([, v]) => v !== "" && v !== null && !(Array.isArray(v) && !v.length)));
      const batch = await api<Batch>("/batches", { body: { note, hints: cleanHints, auto_commit: mode === "confident" ? "confident" : "none", analyze: true } });
      let sent = 0;
      let failed = 0;
      for (let i = 0; i < files.length; i += CHUNK) {
        const chunk = files.slice(i, i + CHUNK);
        const form = new FormData();
        chunk.forEach((f) => form.append("files", f.file, f.path.replace(/\//g, "__")));
        setStage(`Uploading ${Math.min(i + CHUNK, files.length)} of ${files.length}…`);
        const base = sent;
        const r = await uploadForm<{ results: { error?: string }[] }>(`/api/v1/batches/${batch.id}/photos`, form, (l, t) => setProgress((base + (l / t) * chunk.length) / files.length));
        failed += r.results.filter((x) => x.error).length;
        sent += chunk.length;
        setProgress(sent / files.length);
      }
      qc.invalidateQueries();
      if (failed) toast(`${failed} file${failed === 1 ? "" : "s"} could not be read`, "error");
      nav(`/inbox/${batch.id}`);
    } catch (e: any) {
      toast(e.message, "error");
      setBusy(false);
    }
  };

  const hint = (k: string) => ({ value: hints[k] ?? "", onChange: (e: any) => setHints((h) => ({ ...h, [k]: e.target.value })) });
  const listHint = (k: string, v: string) => setHints((h) => ({ ...h, [k]: (h[k] || []).includes(v) ? h[k].filter((x: string) => x !== v) : [...(h[k] || []), v] }));

  return (
    <div className="mx-auto max-w-5xl px-4 pt-5 sm:px-6 lg:px-8 lg:pt-8">
      <h1 className="font-display text-3xl sm:text-4xl">Add clothes</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted">
        Drop a whole folder — flat-lays, photos of you wearing things, price tags and receipts all mixed together. Each piece is detected, matched across
        photos, cut out and filled in. You review everything before it lands in your closet.
      </p>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        className={cx(
          "mt-6 flex flex-col items-center justify-center rounded-3xl border-2 border-dashed px-6 py-12 text-center transition-colors",
          drag ? "border-accent bg-accent-soft" : "border-[#d8d2c8] bg-white",
        )}
      >
        <div className="grid size-14 place-items-center rounded-2xl bg-canvas">
          <UploadIcon className="size-6 text-ink-2" />
        </div>
        <div className="mt-4 font-medium">Drop photos or folders here</div>
        <div className="mt-1 text-sm text-muted">JPG, PNG, HEIC or WebP · up to {MAX_FILES} at once · subfolders included</div>
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          <Button onClick={() => dirRef.current?.click()}>
            <FolderOpen className="size-4" /> Choose a folder
          </Button>
          <Button onClick={() => fileRef.current?.click()}>
            <ImagePlus className="size-4" /> Choose photos
          </Button>
        </div>
        <input ref={fileRef} type="file" accept="image/*,.heic,.heif" multiple className="hidden" onChange={(e) => fromInput(e.target.files)} />
        <input ref={dirRef} type="file" multiple className="hidden" onChange={(e) => fromInput(e.target.files)} />
      </div>

      {files.length > 0 && (
        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
          <Card className="p-4">
            <div className="mb-3 flex items-center justify-between text-sm">
              <span>
                <b>{files.length}</b> photos · {(size / 1024 / 1024).toFixed(1)} MB
                {folders.size > 1 && <span className="text-muted"> · {folders.size} folders</span>}
              </span>
              {!busy && (
                <button className="text-xs text-muted hover:text-ink" onClick={() => setFiles([])}>
                  Clear
                </button>
              )}
            </div>
            <div className="grid max-h-[460px] grid-cols-4 gap-2 overflow-y-auto pr-1 scrollbar-thin sm:grid-cols-6">
              {files.map((f, i) => (
                <div key={f.path + i} className="group relative aspect-square overflow-hidden rounded-xl bg-canvas">
                  {/\.(heic|heif)$/i.test(f.file.name) ? (
                    <div className="grid size-full place-items-center p-1 text-center text-[10px] text-muted">{f.file.name}</div>
                  ) : (
                    <img src={f.url} loading="lazy" className="size-full object-cover" alt="" />
                  )}
                  {!busy && (
                    <button
                      onClick={() => setFiles((cur) => cur.filter((_, j) => j !== i))}
                      className="absolute right-1 top-1 hidden rounded-full bg-ink/70 p-0.5 text-white group-hover:block"
                    >
                      <X className="size-3.5" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </Card>

          <div className="space-y-4">
            <Card className="space-y-4 p-4">
              <Field label="Anything to know about these? (optional)" hint="The AI reads this, e.g. “all from the Zara sale in Delhi, Oct 2025” or “the blue kurta was a gift from Mom”.">
                <Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
              </Field>
              <button className="text-sm font-medium text-ink underline-offset-2 hover:underline" onClick={() => setShowHints(!showHints)}>
                {showHints ? "Hide" : "Add"} purchase details for this import
              </button>
              {showHints && (
                <div className="space-y-3 rounded-2xl bg-canvas p-3">
                  <p className="flex gap-1.5 text-xs text-ink-2">
                    <Info className="mt-0.5 size-3.5 shrink-0" />
                    These apply to <b>every</b> item found in this import. Leave blank if they differ — you can set them per item when reviewing, and tags
                    or receipts in the photos are read automatically.
                  </p>
                  <div className="grid grid-cols-2 gap-2">
                    <Field label="Store">
                      <Input {...hint("store")} />
                    </Field>
                    <Field label="Bought on">
                      <Input type="date" {...hint("purchase_date")} />
                    </Field>
                    <Field label="Price paid (each)">
                      <Input type="number" inputMode="decimal" {...hint("price")} />
                    </Field>
                    <Field label="Original price / MRP">
                      <Input type="number" inputMode="decimal" {...hint("original_price")} />
                    </Field>
                    <Field label="Brand">
                      <Input {...hint("brand")} />
                    </Field>
                    <Field label="Gift from">
                      <Input {...hint("gifted_by")} />
                    </Field>
                  </div>
                  <Field label="Occasions">
                    <div className="flex flex-wrap gap-1.5">
                      {me.taxonomy.occasions.slice(0, 12).map((o) => (
                        <Chip key={o} active={(hints.occasions || []).includes(o)} onClick={() => listHint("occasions", o)}>
                          {cap(o)}
                        </Chip>
                      ))}
                    </div>
                  </Field>
                </div>
              )}
              <Field label="When it's done">
                <Segmented
                  value={mode}
                  onChange={setMode}
                  options={[
                    { value: "review", label: "Let me review" },
                    { value: "confident", label: "Add sure ones" },
                  ]}
                />
              </Field>
              {!me.vision && (
                <p className="rounded-xl bg-[#fdf3e2] p-3 text-xs text-warn">Photo analysis isn't configured on this server, so photos will wait in review for you to sort by hand.</p>
              )}
            </Card>
            {busy ? (
              <Card className="space-y-3 p-4">
                <div className="text-sm">{stage}</div>
                <Progress value={progress} />
                <p className="text-xs text-muted">Keep this tab open until the upload finishes. Analysis then continues on the server.</p>
              </Card>
            ) : (
              <Button variant="primary" size="lg" className="w-full" onClick={start}>
                Upload {files.length} photo{files.length === 1 ? "" : "s"}
              </Button>
            )}
          </div>
        </div>
      )}

      <div className="mt-10 grid gap-3 pb-10 sm:grid-cols-3">
        {[
          ["Mix everything", "Flat-lays, mirror selfies, tags and receipts can share a folder. Photos of the same piece are grouped."],
          ["Purchase details only from you", "Store, price and MRP come from what you type, a tag or a receipt — never guessed."],
          ["Agents can do this too", "Claude or Codex can import a folder through the wardrobe MCP. See Settings → Agents."],
        ].map(([t, d]) => (
          <div key={t} className="rounded-2xl bg-canvas p-4">
            <div className="text-sm font-medium">{t}</div>
            <div className="mt-1 text-xs leading-relaxed text-muted">{d}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
