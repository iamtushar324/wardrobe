import type { Item, Taxonomy } from "../api";
import { Badge, cap, Chip, cx, Field, Input, Select, Swatch, Textarea } from "../ui";

const PROV_LABEL: Record<string, string> = { user: "you", tag: "tag", receipt: "receipt", ai: "AI", agent: "agent" };

export function Prov({ source }: { source?: string }) {
  if (!source) return null;
  return <Badge tone={source === "user" ? "neutral" : "accent"}>{PROV_LABEL[source] || source}</Badge>;
}

export type Draft = Partial<Item> & { colors?: { name: string; hex: string; share: number | null }[] };

function ListChips({ values, options, onChange }: { values: string[]; options: string[]; onChange: (v: string[]) => void }) {
  const all = Array.from(new Set([...options, ...values]));
  return (
    <div className="flex flex-wrap gap-1.5">
      {all.map((o) => (
        <Chip key={o} active={values.includes(o)} onClick={() => onChange(values.includes(o) ? values.filter((v) => v !== o) : [...values, o])}>
          {cap(o)}
        </Chip>
      ))}
    </div>
  );
}

export function ColorPicker({ value, palette, onChange }: { value: { name: string; hex: string }[]; palette: Record<string, string>; onChange: (v: { name: string; hex: string; share: number | null }[]) => void }) {
  const names = value.map((c) => c.name);
  return (
    <div className="flex flex-wrap gap-2">
      {Object.entries(palette).map(([name, hex]) => {
        const on = names.includes(name);
        return (
          <button
            key={name}
            type="button"
            title={cap(name)}
            onClick={() =>
              onChange(on ? value.filter((c) => c.name !== name).map((c) => ({ ...c, share: null })) : [...value.map((c) => ({ ...c, share: null })), { name, hex, share: null }])
            }
            className={cx("rounded-full p-0.5", on && "ring-2 ring-ink ring-offset-1")}
          >
            <Swatch hex={hex} size={22} />
          </button>
        );
      })}
    </div>
  );
}

/** Editable item fields. `value` is the draft; `onChange` merges a patch. */
export function ItemFields({ value, taxonomy, onChange, provenance = {}, compact }: {
  value: Draft;
  taxonomy: Taxonomy;
  onChange: (patch: Draft) => void;
  provenance?: Record<string, string>;
  compact?: boolean;
}) {
  const cats = Object.keys(taxonomy.categories);
  const subs = value.category ? taxonomy.categories[value.category] || [] : [];
  const label = (text: string, key: string) => (
    <span className="flex items-center gap-1.5">
      {text} <Prov source={provenance[key]} />
    </span>
  );
  return (
    <div className="space-y-5">
      <Field label="Name">
        <Input value={value.name || ""} onChange={(e) => onChange({ name: e.target.value })} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Category">
          <Select value={value.category || ""} placeholder="—" options={cats} onChange={(v) => onChange({ category: v || null, subcategory: null })} />
        </Field>
        <Field label="Type">
          <Select value={value.subcategory || ""} placeholder="—" options={Array.from(new Set([...subs, ...(value.subcategory ? [value.subcategory] : [])]))} onChange={(v) => onChange({ subcategory: v || null })} />
        </Field>
      </div>
      <Field label="Colours">
        <ColorPicker value={value.colors || []} palette={taxonomy.palette} onChange={(colors) => onChange({ colors })} />
      </Field>
      <Field label="Seasons">
        <ListChips values={value.seasons || []} options={taxonomy.seasons} onChange={(seasons) => onChange({ seasons })} />
      </Field>
      <Field label="Occasions">
        <ListChips values={value.occasions || []} options={taxonomy.occasions} onChange={(occasions) => onChange({ occasions })} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label={label("Brand", "brand")}>
          <Input value={value.brand || ""} onChange={(e) => onChange({ brand: e.target.value })} />
        </Field>
        <Field label={label("Size", "size")}>
          <Input value={value.size || ""} onChange={(e) => onChange({ size: e.target.value })} />
        </Field>
        <Field label={label("Material", "material")}>
          <Input list="materials" value={value.material || ""} onChange={(e) => onChange({ material: e.target.value })} />
          <datalist id="materials">
            {taxonomy.materials.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </Field>
        <Field label="Pattern">
          <Select value={value.pattern || ""} placeholder="—" options={taxonomy.patterns} onChange={(v) => onChange({ pattern: v || null })} />
        </Field>
        <Field label="Fit">
          <Select value={value.fit || ""} placeholder="—" options={taxonomy.fits} onChange={(v) => onChange({ fit: v || null })} />
        </Field>
        <Field label="Status">
          <Select value={value.status || "active"} options={taxonomy.statuses} onChange={(v) => onChange({ status: v })} />
        </Field>
      </div>
      {!compact && (
        <>
          <Field label="Style words" hint="Comma separated, e.g. minimal, streetwear, classic">
            <Input value={(value.styles || []).join(", ")} onChange={(e) => onChange({ styles: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
          </Field>
          <Field label="Where it lives">
            <Input value={value.location || ""} placeholder="e.g. bedroom wardrobe, left shelf" onChange={(e) => onChange({ location: e.target.value })} />
          </Field>
        </>
      )}
      <div className="rounded-2xl bg-canvas p-4">
        <div className="mb-3 text-[12px] font-semibold uppercase tracking-wide text-ink-2">Purchase (optional)</div>
        <div className="grid grid-cols-2 gap-3">
          <Field label={label("Store", "store")}>
            <Input value={value.store || ""} onChange={(e) => onChange({ store: e.target.value })} />
          </Field>
          <Field label={label("Bought on", "purchase_date")}>
            <Input type="date" value={value.purchase_date || ""} onChange={(e) => onChange({ purchase_date: e.target.value })} />
          </Field>
          <Field label={label("Price paid", "price")}>
            <Input type="number" inputMode="decimal" value={value.price ?? ""} onChange={(e) => onChange({ price: e.target.value === "" ? null : Number(e.target.value) })} />
          </Field>
          <Field label={label("Original price / MRP", "original_price")}>
            <Input
              type="number"
              inputMode="decimal"
              value={value.original_price ?? ""}
              onChange={(e) => onChange({ original_price: e.target.value === "" ? null : Number(e.target.value) })}
            />
          </Field>
          <Field label="Currency">
            <Input value={value.currency || ""} placeholder="INR" maxLength={3} onChange={(e) => onChange({ currency: e.target.value.toUpperCase() })} />
          </Field>
          <Field label="Gift from">
            <Input value={value.gifted_by || ""} onChange={(e) => onChange({ gifted_by: e.target.value })} />
          </Field>
        </div>
      </div>
      {!compact && (
        <Field label="Notes">
          <Textarea rows={3} value={value.notes || ""} onChange={(e) => onChange({ notes: e.target.value })} />
        </Field>
      )}
    </div>
  );
}

export const EDITABLE: (keyof Item)[] = [
  "name", "category", "subcategory", "colors", "seasons", "occasions", "styles", "brand", "size", "material", "pattern", "fit", "status",
  "location", "store", "purchase_date", "price", "original_price", "currency", "gifted_by", "notes", "tags",
];

export function diff(item: Item, draft: Draft): Draft {
  const out: any = {};
  for (const k of EDITABLE) {
    if (!(k in draft)) continue;
    const a = JSON.stringify((item as any)[k] ?? null);
    const b = JSON.stringify((draft as any)[k] ?? null);
    if (a !== b) out[k] = (draft as any)[k];
  }
  return out;
}
