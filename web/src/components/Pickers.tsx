import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, Sparkles, User } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type Item, type Photo, type Studio, type Template } from "../api";
import { TemplateIcon } from "../icons";
import { Badge, Button, cx, Input, Modal, Spinner, Textarea, useDebounced, useToast } from "../ui";
import { ItemCard, Masonry, PhotoTile } from "./Cards";

export function ItemPicker({ open, onClose, onPick, multi = true, title = "Choose items", max = 50, exclude = [] }: {
  open: boolean;
  onClose: () => void;
  onPick: (ids: string[], items: Item[]) => void;
  multi?: boolean;
  title?: string;
  max?: number;
  exclude?: string[];
}) {
  const [q, setQ] = useState("");
  const dq = useDebounced(q, 250);
  const [sel, setSel] = useState<Item[]>([]);
  const res = useQuery({
    queryKey: ["items-picker", dq],
    queryFn: () => api<{ items: Item[]; total: number }>("/items", { query: { q: dq, limit: 120 } }),
    enabled: open,
  });
  const toggle = (it: Item) => {
    if (!multi) {
      onPick([it.id], [it]);
      onClose();
      return;
    }
    setSel((s) => (s.some((x) => x.id === it.id) ? s.filter((x) => x.id !== it.id) : s.length >= max ? s : [...s, it]));
  };
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      wide
      footer={
        multi && (
          <>
            <span className="mr-auto self-center text-sm text-muted">{sel.length} selected{max < 50 ? ` (up to ${max})` : ""}</span>
            <Button onClick={onClose}>Cancel</Button>
            <Button
              variant="primary"
              disabled={!sel.length}
              onClick={() => {
                onPick(sel.map((s) => s.id), sel);
                setSel([]);
                onClose();
              }}
            >
              Use {sel.length || ""} {sel.length === 1 ? "item" : "items"}
            </Button>
          </>
        )
      }
    >
      <div className="relative mb-4">
        <Search className="absolute left-3.5 top-3 size-4 text-muted" />
        <Input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search your items" className="rounded-full pl-10" />
      </div>
      {res.isLoading ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-x-3 gap-y-4 sm:grid-cols-4 md:grid-cols-5">
          {res.data?.items
            .filter((i) => !exclude.includes(i.id))
            .map((it) => (
              <ItemCard key={it.id} item={it} selected={multi ? sel.some((s) => s.id === it.id) : undefined} onSelect={toggle} />
            ))}
        </div>
      )}
    </Modal>
  );
}

export function PhotoPicker({ open, onClose, onPick, query, title = "Choose a photo" }: {
  open: boolean;
  onClose: () => void;
  onPick: (photo: Photo) => void;
  query: Record<string, string>;
  title?: string;
}) {
  const res = useQuery({
    queryKey: ["photos-picker", query],
    queryFn: () => api<{ photos: Photo[] }>("/photos", { query: { ...query, limit: 120 } }),
    enabled: open,
  });
  return (
    <Modal open={open} onClose={onClose} title={title} wide>
      {res.isLoading ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : res.data?.photos.length ? (
        <Masonry>
          {res.data.photos.map((p) => (
            <PhotoTile
              key={p.id}
              photo={p}
              onClick={() => {
                onPick(p);
                onClose();
              }}
            />
          ))}
        </Masonry>
      ) : (
        <p className="py-10 text-center text-sm text-muted">No photos to choose from yet.</p>
      )}
    </Modal>
  );
}

export function TemplateCard({ t, selected, onClick, small }: { t: Template; selected?: boolean; onClick?: () => void; small?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        "flex h-full flex-col rounded-2xl border p-4 text-left transition-colors",
        selected ? "border-ink bg-ink text-paper" : "border-line bg-white hover:border-[#cfc9bf]",
      )}
    >
      <div className="flex items-center gap-2">
        <span className={cx("grid size-8 place-items-center rounded-xl", selected ? "bg-white/15" : "bg-canvas")}>
          <TemplateIcon name={t.icon} className="size-4" />
        </span>
        <span className="font-medium leading-tight">{t.name}</span>
      </div>
      {!small && <p className={cx("mt-2 text-xs leading-relaxed", selected ? "text-[#d9d4cb]" : "text-muted")}>{t.description}</p>}
      <div className="mt-auto flex flex-wrap gap-1 pt-3">
        {t.needs_person && (
          <Badge tone={selected ? "dark" : "accent"}>
            <User className="size-3" /> You
          </Badge>
        )}
        {t.multi_item && <Badge tone={selected ? "dark" : "neutral"}>Outfit</Badge>}
        {t.custom && <Badge tone={selected ? "dark" : "neutral"}>Custom</Badge>}
      </div>
    </button>
  );
}

/** Queue AI pictures for one or more items. */
export function GenerateDialog({ open, onClose, itemIds, initialTemplate }: { open: boolean; onClose: () => void; itemIds: string[]; initialTemplate?: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const studio = useQuery({ queryKey: ["studio"], queryFn: () => api<Studio>("/studio"), enabled: open });
  const [tid, setTid] = useState(initialTemplate || "");
  const [extra, setExtra] = useState("");
  const t = studio.data?.templates.find((x) => x.id === tid);
  const noModel = !!t?.needs_person && !studio.data?.prefs.model_photo_ids.length;
  const run = useMutation({
    mutationFn: () => api<{ jobs: any[] }>("/studio/jobs", { body: { template: tid, item_ids: itemIds, extra } }),
    onSuccess: (r) => {
      toast(`${r.jobs.length} picture${r.jobs.length === 1 ? "" : "s"} queued`);
      qc.invalidateQueries({ queryKey: ["studio"] });
      qc.invalidateQueries({ queryKey: ["me"] });
      onClose();
    },
    onError: (e: any) => toast(e.message, "error"),
  });
  const templates = (studio.data?.templates || []).filter((x) => !x.tryon); // try-on has its own page
  const groups = Array.from(new Set(templates.map((x) => x.group)));
  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title={
        <span className="flex items-center gap-2">
          <Sparkles className="size-5" /> Make AI pictures
        </span>
      }
      footer={
        <>
          {studio.data && !studio.data.available && <span className="mr-auto self-center text-xs text-warn">Will wait: {studio.data.reason}</span>}
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!tid || noModel || itemIds.length === 0} loading={run.isPending} onClick={() => run.mutate()}>
            Queue {t?.multi_item ? "1 picture" : `${itemIds.length} picture${itemIds.length === 1 ? "" : "s"}`}
          </Button>
        </>
      }
    >
      {!studio.data ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : (
        <div className="space-y-6">
          {groups.map((g) => (
            <div key={g}>
              <div className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted">{g}</div>
              <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
                {templates
                  .filter((x) => x.group === g && (itemIds.length > 1 || !x.multi_item))
                  .map((x) => (
                    <TemplateCard key={x.id} t={x} selected={tid === x.id} onClick={() => setTid(x.id)} />
                  ))}
              </div>
            </div>
          ))}
          {noModel && (
            <div className="rounded-xl bg-[#fdf3e2] p-3 text-sm text-warn">
              This picture puts you in the clothes, so Studio needs a photo of you first.{" "}
              <Link to="/studio#model" className="underline" onClick={onClose}>
                Choose a model photo
              </Link>
            </div>
          )}
          <div>
            <div className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted">Anything to add? (optional)</div>
            <Textarea rows={2} value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="e.g. tucked in, rolled sleeves, at a beach in Goa" />
          </div>
        </div>
      )}
    </Modal>
  );
}
