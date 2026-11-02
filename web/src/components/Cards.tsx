import { Heart, Sparkles, User } from "lucide-react";
import { Link } from "react-router-dom";
import type { Img, Item, Photo } from "../api";
import { Badge, cap, cx, money, Swatch } from "../ui";

export function Thumb({ img, className, fit, alt = "" }: { img: Img | null | undefined; className?: string; fit?: "contain" | "cover"; alt?: string }) {
  if (!img) return <div className={cx("bg-canvas", className)} />;
  const contain = fit ? fit === "contain" : !!img.cutout;
  return (
    <img
      src={img.md}
      alt={alt}
      loading="lazy"
      decoding="async"
      className={cx(contain ? "object-contain p-[8%]" : "object-cover", "bg-canvas", className)}
    />
  );
}

export function ItemCard({ item, selected, onSelect }: { item: Item; selected?: boolean; onSelect?: (item: Item) => void }) {
  const body = (
    <>
      <div className="relative aspect-[4/5] overflow-hidden rounded-2xl bg-canvas">
        <Thumb img={item.cover} alt={item.name} className="size-full transition-transform duration-300 group-hover:scale-[1.03]" />
        <div className="absolute left-2 top-2 flex gap-1">
          {item.cover?.ai && (
            <Badge tone="dark">
              <Sparkles className="size-3" /> AI
            </Badge>
          )}
          {item.status !== "active" && <Badge tone="dark">{cap(item.status)}</Badge>}
        </div>
        {item.favorite && <Heart className="absolute right-2.5 top-2.5 size-4 fill-[#d64545] text-[#d64545]" />}
        {!!item.worn_count_photos && (
          <span className="absolute bottom-2 right-2 inline-flex items-center gap-1 rounded-full bg-white/85 px-2 py-0.5 text-[11px] text-ink-2 backdrop-blur">
            <User className="size-3" /> {item.worn_count_photos}
          </span>
        )}
        {selected !== undefined && (
          <span
            className={cx(
              "absolute right-2 top-2 grid size-6 place-items-center rounded-full border-2 text-xs font-bold",
              selected ? "border-ink bg-ink text-paper" : "border-white bg-white/70",
            )}
          >
            {selected ? "✓" : ""}
          </span>
        )}
      </div>
      <div className="px-1 pt-2.5">
        <div className="truncate text-[14px] font-medium leading-tight">{item.name}</div>
        <div className="mt-1 flex items-center gap-1.5 text-xs text-muted">
          <span className="flex -space-x-1">
            {item.colors.slice(0, 3).map((c) => (
              <Swatch key={c.name} hex={c.hex} size={11} />
            ))}
          </span>
          <span className="truncate">{[item.brand, item.subcategory || item.category].filter(Boolean).map((s) => cap(s)).join(" · ")}</span>
          {item.price !== null && <span className="ml-auto shrink-0 tabular-nums">{money(item.price, item.currency)}</span>}
        </div>
      </div>
    </>
  );
  if (onSelect)
    return (
      <button type="button" className={cx("group text-left", selected && "opacity-100")} onClick={() => onSelect(item)}>
        {body}
      </button>
    );
  return (
    <Link to={`/item/${item.id}`} className="group fade-in block">
      {body}
    </Link>
  );
}

export function PhotoTile({ photo, onClick, selected }: { photo: Photo; onClick?: () => void; selected?: boolean }) {
  const ratio = photo.width && photo.height ? photo.width / photo.height : 0.8;
  const inner = (
    <div className="group relative mb-3 overflow-hidden rounded-2xl bg-canvas" style={{ aspectRatio: String(ratio) }}>
      <img src={photo.image.md} alt="" loading="lazy" decoding="async" className="size-full object-cover transition-transform duration-300 group-hover:scale-[1.02]" />
      <div className="absolute left-2 top-2 flex gap-1">
        {photo.ai && (
          <Badge tone="dark">
            <Sparkles className="size-3" /> AI
          </Badge>
        )}
      </div>
      {photo.links && photo.links.length > 0 && (
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/55 to-transparent p-2.5 pt-8 text-[12px] leading-tight text-white opacity-0 transition-opacity group-hover:opacity-100">
          {photo.links
            .filter((l) => l.item)
            .slice(0, 3)
            .map((l) => l.item!.name)
            .join(" · ")}
        </div>
      )}
      {selected !== undefined && (
        <span
          className={cx(
            "absolute right-2 top-2 grid size-6 place-items-center rounded-full border-2 text-xs font-bold",
            selected ? "border-ink bg-ink text-paper" : "border-white bg-white/70",
          )}
        >
          {selected ? "✓" : ""}
        </span>
      )}
    </div>
  );
  if (onClick)
    return (
      <button type="button" className="block w-full break-inside-avoid text-left" onClick={onClick}>
        {inner}
      </button>
    );
  return (
    <Link to={`/photo/${photo.id}`} className="fade-in block break-inside-avoid">
      {inner}
    </Link>
  );
}

export function Masonry({ children }: { children: React.ReactNode }) {
  return <div className="columns-2 gap-3 sm:columns-3 xl:columns-4 2xl:columns-5">{children}</div>;
}

export function ItemGrid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 gap-x-3 gap-y-6 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6">{children}</div>;
}
