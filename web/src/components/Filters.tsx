import { ChevronDown, X } from "lucide-react";
import { ReactNode, useState } from "react";
import type { Facets, Taxonomy } from "../api";
import { cap, Chip, cx, Swatch, Toggle } from "../ui";

export type FilterState = Record<string, string>;

export const FILTER_KEYS = ["category", "color", "season", "occasion", "brand", "status", "style", "size", "material", "pattern"];
export const FLAG_KEYS = ["favorite", "has_worn", "has_ai", "no_photo"];

function csv(v: string | undefined): string[] {
  return v ? v.split(",").filter(Boolean) : [];
}

function Section({ title, children, defaultOpen = true, count }: { title: string; children: ReactNode; defaultOpen?: boolean; count?: number }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-line py-4 last:border-0">
      <button className="flex w-full items-center justify-between text-[12px] font-semibold uppercase tracking-wide text-ink-2" onClick={() => setOpen(!open)}>
        <span>
          {title}
          {count ? <span className="ml-1.5 rounded-full bg-ink px-1.5 text-[10px] text-paper">{count}</span> : null}
        </span>
        <ChevronDown className={cx("size-4 text-muted transition-transform", open && "rotate-180")} />
      </button>
      {open && <div className="mt-3">{children}</div>}
    </div>
  );
}

export function FilterPanel({ filters, facets, taxonomy, onChange }: {
  filters: FilterState;
  facets: Facets;
  taxonomy: Taxonomy;
  onChange: (key: string, value: string | null) => void;
}) {
  const toggle = (key: string, value: string) => {
    const cur = csv(filters[key]);
    const next = cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value];
    onChange(key, next.length ? next.join(",") : null);
  };
  const facetList = (key: string, base: string[] = []) => {
    const counts = Object.fromEntries((facets[key] || []).map((f) => [f.value, f.count]));
    const values = Array.from(new Set([...(facets[key] || []).map((f) => f.value), ...base]));
    return values.map((v) => ({ value: v, count: counts[v] || 0 }));
  };
  const [allBrands, setAllBrands] = useState(false);
  const brands = facetList("brand");
  return (
    <div className="text-sm">
      <Section title="Category" count={csv(filters.category).length}>
        <div className="flex flex-col gap-0.5">
          {facetList("category", Object.keys(taxonomy.categories))
            .filter((f) => f.count > 0 || csv(filters.category).includes(f.value))
            .map((f) => {
              const on = csv(filters.category).includes(f.value);
              return (
                <button
                  key={f.value}
                  onClick={() => toggle("category", f.value)}
                  className={cx("flex h-8 items-center justify-between rounded-lg px-2.5 text-left transition-colors", on ? "bg-ink text-paper" : "hover:bg-canvas")}
                >
                  <span>{cap(f.value)}</span>
                  <span className={cx("text-xs tabular-nums", on ? "text-[#cfc9bf]" : "text-muted")}>{f.count}</span>
                </button>
              );
            })}
        </div>
      </Section>
      <Section title="Colour" count={csv(filters.color).length}>
        <div className="grid grid-cols-6 gap-2">
          {facetList("color")
            .filter((f) => f.count > 0 || csv(filters.color).includes(f.value))
            .map((f) => {
              const on = csv(filters.color).includes(f.value);
              return (
                <button key={f.value} title={`${cap(f.value)} (${f.count})`} onClick={() => toggle("color", f.value)} className="flex flex-col items-center gap-1">
                  <Swatch hex={taxonomy.palette[f.value] || "#999"} size={26} ring={on} />
                  <span className="max-w-full truncate text-[10px] text-muted">{f.value}</span>
                </button>
              );
            })}
        </div>
        {!(facets.color || []).length && <p className="text-xs text-muted">Colours appear once items have them.</p>}
      </Section>
      <Section title="Season" count={csv(filters.season).length}>
        <div className="flex flex-wrap gap-1.5">
          {facetList("season", taxonomy.seasons).map((f) => (
            <Chip key={f.value} active={csv(filters.season).includes(f.value)} count={f.count} onClick={() => toggle("season", f.value)}>
              {cap(f.value)}
            </Chip>
          ))}
        </div>
      </Section>
      <Section title="Occasion" count={csv(filters.occasion).length}>
        <div className="flex flex-wrap gap-1.5">
          {facetList("occasion", taxonomy.occasions)
            .filter((f) => f.count > 0 || csv(filters.occasion).includes(f.value) || taxonomy.occasions.slice(0, 8).includes(f.value))
            .map((f) => (
              <Chip key={f.value} active={csv(filters.occasion).includes(f.value)} count={f.count} onClick={() => toggle("occasion", f.value)}>
                {cap(f.value)}
              </Chip>
            ))}
        </div>
      </Section>
      {brands.length > 0 && (
        <Section title="Brand" count={csv(filters.brand).length} defaultOpen={false}>
          <div className="flex flex-col gap-0.5">
            {(allBrands ? brands : brands.slice(0, 8)).map((f) => {
              const on = csv(filters.brand).includes(f.value);
              return (
                <button
                  key={f.value}
                  onClick={() => toggle("brand", f.value)}
                  className={cx("flex h-8 items-center justify-between rounded-lg px-2.5 text-left", on ? "bg-ink text-paper" : "hover:bg-canvas")}
                >
                  <span className="truncate">{cap(f.value)}</span>
                  <span className={cx("text-xs tabular-nums", on ? "text-[#cfc9bf]" : "text-muted")}>{f.count}</span>
                </button>
              );
            })}
            {brands.length > 8 && (
              <button className="mt-1 text-left text-xs text-muted underline" onClick={() => setAllBrands(!allBrands)}>
                {allBrands ? "Show fewer" : `Show all ${brands.length}`}
              </button>
            )}
          </div>
        </Section>
      )}
      {(facets.style || []).length > 0 && (
        <Section title="Style" count={csv(filters.style).length} defaultOpen={false}>
          <div className="flex flex-wrap gap-1.5">
            {facetList("style").map((f) => (
              <Chip key={f.value} active={csv(filters.style).includes(f.value)} count={f.count} onClick={() => toggle("style", f.value)}>
                {cap(f.value)}
              </Chip>
            ))}
          </div>
        </Section>
      )}
      <Section title="Status" count={csv(filters.status).length} defaultOpen={false}>
        <div className="flex flex-wrap gap-1.5">
          {[...taxonomy.statuses, "all"].map((s) => (
            <Chip key={s} active={csv(filters.status).includes(s)} onClick={() => toggle("status", s)}>
              {s === "all" ? "Everything (incl. given away)" : cap(s)}
            </Chip>
          ))}
        </div>
      </Section>
      <Section title="Show only" defaultOpen>
        <div className="flex flex-col gap-3">
          <Toggle checked={filters.favorite === "true"} onChange={(v) => onChange("favorite", v ? "true" : null)} label="Favourites" />
          <Toggle checked={filters.has_worn === "true"} onChange={(v) => onChange("has_worn", v ? "true" : null)} label="Has a photo of me wearing it" />
          <Toggle checked={filters.has_ai === "true"} onChange={(v) => onChange("has_ai", v ? "true" : null)} label="Has AI pictures" />
          <Toggle checked={filters.no_photo === "true"} onChange={(v) => onChange("no_photo", v ? "true" : null)} label="No photo yet" />
        </div>
      </Section>
    </div>
  );
}

export function ActiveChips({ filters, onChange, onClear }: { filters: FilterState; onChange: (k: string, v: string | null) => void; onClear: () => void }) {
  const chips: { key: string; value: string; label: string }[] = [];
  for (const k of FILTER_KEYS) for (const v of csv(filters[k])) chips.push({ key: k, value: v, label: cap(v) });
  const flagLabels: Record<string, string> = { favorite: "Favourites", has_worn: "Worn photo", has_ai: "Has AI", no_photo: "No photo" };
  for (const k of FLAG_KEYS) if (filters[k] === "true") chips.push({ key: k, value: "true", label: flagLabels[k] });
  if (filters.q) chips.push({ key: "q", value: filters.q, label: `“${filters.q}”` });
  if (!chips.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {chips.map((c) => (
        <Chip
          key={c.key + c.value}
          active
          onClick={() => {}}
          onRemove={() => {
            if (FLAG_KEYS.includes(c.key) || c.key === "q") onChange(c.key, null);
            else {
              const next = csv(filters[c.key]).filter((v) => v !== c.value);
              onChange(c.key, next.length ? next.join(",") : null);
            }
          }}
        >
          {c.label}
        </Chip>
      ))}
      <button className="ml-1 inline-flex items-center gap-1 text-xs text-muted hover:text-ink" onClick={onClear}>
        <X className="size-3.5" /> Clear all
      </button>
    </div>
  );
}
