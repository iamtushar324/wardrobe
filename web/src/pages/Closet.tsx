import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Images, LayoutGrid, Plus, Search, Shirt, SlidersHorizontal, User } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type Facets, type Item, type Photo } from "../api";
import { useMe } from "../App";
import { ItemCard, ItemGrid, Masonry, PhotoTile } from "../components/Cards";
import { ActiveChips, FILTER_KEYS, FLAG_KEYS, FilterPanel, type FilterState } from "../components/Filters";
import { Button, Empty, Input, Modal, Segmented, Select, Spinner, useDebounced } from "../ui";

const PAGE = 60;
type View = "items" | "worn" | "photos";

const SORTS = [
  { value: "recent", label: "Recently added" },
  { value: "category", label: "Category" },
  { value: "name", label: "Name" },
  { value: "worn_most", label: "Most worn" },
  { value: "worn_least", label: "Least worn" },
  { value: "price_high", label: "Price: high to low" },
  { value: "price_low", label: "Price: low to high" },
  { value: "oldest", label: "Oldest" },
];

function useSentinel(onHit: () => void, enabled: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!enabled || !ref.current) return;
    const io = new IntersectionObserver((e) => e[0].isIntersecting && onHit(), { rootMargin: "800px" });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [enabled, onHit]);
  return ref;
}

export default function Closet() {
  const me = useMe();
  const [params, setParams] = useSearchParams();
  const view = (params.get("view") as View) || "items";
  const source = params.get("source") || "all";
  const [showFilters, setShowFilters] = useState(false);
  const [q, setQ] = useState(params.get("q") || "");
  const dq = useDebounced(q, 300);

  const filters: FilterState = useMemo(() => {
    const f: FilterState = {};
    for (const k of [...FILTER_KEYS, ...FLAG_KEYS, "q", "sort", "kind"]) {
      const v = params.get(k);
      if (v) f[k] = v;
    }
    return f;
  }, [params]);

  useEffect(() => {
    if ((params.get("q") || "") !== dq) set("q", dq || null);
  }, [dq]);

  function set(key: string, value: string | null) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }
  const clear = () => {
    const next = new URLSearchParams();
    if (view !== "items") next.set("view", view);
    setQ("");
    setParams(next, { replace: true });
  };

  const itemQuery = { ...filters };
  const items = useInfiniteQuery({
    queryKey: ["items", itemQuery],
    queryFn: ({ pageParam }) => api<{ total: number; items: Item[]; facets: Facets }>("/items", { query: { ...itemQuery, limit: PAGE, offset: pageParam } }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => (pages.length * PAGE < last.total ? pages.length * PAGE : undefined),
    enabled: view === "items",
  });
  const photoQuery = { ...filters, ...(view === "worn" ? { person: "me", kind: "worn", source } : { source }) };
  const photos = useInfiniteQuery({
    queryKey: ["photos", photoQuery],
    queryFn: ({ pageParam }) =>
      api<{ total: number; photos: Photo[]; kinds: Record<string, number> }>("/photos", { query: { ...photoQuery, limit: PAGE, offset: pageParam } }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => (pages.length * PAGE < last.total ? pages.length * PAGE : undefined),
    enabled: view !== "items",
  });
  const facetQ = useQuery({
    queryKey: ["facets", filters],
    queryFn: () => api<{ total: number; facets: Facets }>("/facets", { query: filters }),
    enabled: view !== "items",
  });
  const facets = (view === "items" ? items.data?.pages[0]?.facets : facetQ.data?.facets) || {};
  const active = view === "items" ? items : photos;
  const total = active.data?.pages[0]?.total;
  const sentinel = useSentinel(() => active.hasNextPage && !active.isFetchingNextPage && active.fetchNextPage(), !!active.hasNextPage);
  const filterCount = [...FILTER_KEYS, ...FLAG_KEYS].filter((k) => filters[k]).length;

  const panel = <FilterPanel filters={filters} facets={facets} taxonomy={me.taxonomy} onChange={set} />;

  return (
    <div className="mx-auto max-w-[1600px] px-4 pt-5 sm:px-6 lg:px-8 lg:pt-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl sm:text-4xl">{me.wardrobe === me.user.id ? "Your closet" : "Closet"}</h1>
          <p className="mt-1 text-sm text-muted">
            {total === undefined ? " " : `${total} ${view === "items" ? (total === 1 ? "piece" : "pieces") : total === 1 ? "photo" : "photos"}`}
            {view === "items" && me.stats.paid_total > 0 && !filterCount ? ` · bought for ₹${Math.round(me.stats.paid_total).toLocaleString("en-IN")}` : ""}
          </p>
        </div>
        <Segmented<View>
          value={view}
          onChange={(v) => set("view", v === "items" ? null : v)}
          options={[
            { value: "items", label: "Items", icon: <Shirt className="size-4" /> },
            { value: "worn", label: "On me", icon: <User className="size-4" /> },
            { value: "photos", label: "Photos", icon: <Images className="size-4" /> },
          ]}
        />
      </div>

      <div className="sticky top-14 z-10 -mx-4 mt-5 bg-paper/90 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6 lg:top-0 lg:-mx-8 lg:px-8">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-3 size-4 text-muted" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search: “linen shirt”, “wedding”, “Levi's”…" className="h-10 rounded-full pl-10" />
          </div>
          <Button className="lg:hidden" onClick={() => setShowFilters(true)}>
            <SlidersHorizontal className="size-4" />
            {filterCount ? <span className="rounded-full bg-ink px-1.5 text-[11px] text-paper">{filterCount}</span> : "Filters"}
          </Button>
          {view === "items" ? (
            <Select className="hidden w-48 sm:block" value={filters.sort || "recent"} onChange={(v) => set("sort", v === "recent" ? null : v)} options={SORTS} />
          ) : (
            <Select
              className="hidden w-44 sm:block"
              value={source}
              onChange={(v) => set("source", v === "all" ? null : v)}
              options={[
                { value: "all", label: "Real + AI" },
                { value: "real", label: "Real photos" },
                { value: "ai", label: "AI pictures" },
              ]}
            />
          )}
        </div>
        <div className="mt-2.5">
          <ActiveChips filters={filters} onChange={(k, v) => (k === "q" ? (setQ(""), set("q", null)) : set(k, v))} onClear={clear} />
        </div>
      </div>

      <div className="mt-2 flex gap-8">
        <aside className="hidden w-60 shrink-0 lg:block">
          <div className="sticky top-28 max-h-[calc(100vh-8rem)] overflow-y-auto pr-2 scrollbar-thin">{panel}</div>
        </aside>
        <div className="min-w-0 flex-1">
          {active.isLoading ? (
            <ItemGrid>
              {Array.from({ length: 12 }).map((_, i) => (
                <div key={i}>
                  <div className="skeleton aspect-[4/5] rounded-2xl" />
                  <div className="skeleton mt-3 h-3 w-2/3 rounded" />
                </div>
              ))}
            </ItemGrid>
          ) : total === 0 ? (
            filterCount || filters.q ? (
              <Empty icon={<Search className="size-6" />} title="Nothing matches" action={<Button onClick={clear}>Clear filters</Button>}>
                Try fewer filters or a different word.
              </Empty>
            ) : view === "items" ? (
              <Empty
                icon={<LayoutGrid className="size-6" />}
                title="Your closet is empty"
                action={
                  <Link to="/upload">
                    <Button variant="primary">
                      <Plus className="size-4" /> Add your first photos
                    </Button>
                  </Link>
                }
              >
                Drop a folder of photos — flat-lays on the bed, you wearing things, even the price tags. Each piece is found, cut out and
                catalogued for you.
              </Empty>
            ) : (
              <Empty
                icon={<User className="size-6" />}
                title={view === "worn" ? "No photos of you yet" : "No photos yet"}
                action={
                  <Link to={view === "worn" ? "/studio" : "/upload"}>
                    <Button variant="primary">{view === "worn" ? "Make some in Studio" : "Add photos"}</Button>
                  </Link>
                }
              >
                {view === "worn"
                  ? "Add photos of you wearing your clothes, or let Studio picture you in each piece."
                  : "Photos you add or generate show up here."}
              </Empty>
            )
          ) : view === "items" ? (
            <ItemGrid>{items.data?.pages.flatMap((p) => p.items).map((it) => <ItemCard key={it.id} item={it} />)}</ItemGrid>
          ) : (
            <Masonry>{photos.data?.pages.flatMap((p) => p.photos).map((p) => <PhotoTile key={p.id} photo={p} />)}</Masonry>
          )}
          <div ref={sentinel} className="flex justify-center py-10">
            {active.isFetchingNextPage && <Spinner />}
          </div>
        </div>
      </div>

      <Modal open={showFilters} onClose={() => setShowFilters(false)} title="Filters" footer={<Button variant="primary" onClick={() => setShowFilters(false)}>Show {total ?? ""} results</Button>}>
        {view === "items" && (
          <div className="mb-2">
            <Select value={filters.sort || "recent"} onChange={(v) => set("sort", v === "recent" ? null : v)} options={SORTS} />
          </div>
        )}
        {panel}
      </Modal>
    </div>
  );
}
