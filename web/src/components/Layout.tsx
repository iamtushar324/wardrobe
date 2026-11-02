import { useQueryClient } from "@tanstack/react-query";
import { Inbox, LayoutGrid, Settings, Upload, WandSparkles } from "lucide-react";
import { ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { activeWardrobe, setActiveWardrobe } from "../api";
import { useMe } from "../App";
import { cx, Select } from "../ui";

const NAV = [
  { to: "/", label: "Closet", icon: LayoutGrid, end: true },
  { to: "/upload", label: "Add", icon: Upload },
  { to: "/inbox", label: "Review", icon: Inbox, badge: "inbox" },
  { to: "/studio", label: "Studio", icon: WandSparkles, badge: "studio" },
  { to: "/settings", label: "Settings", icon: Settings },
];

export default function Layout({ children }: { children: ReactNode }) {
  const me = useMe();
  const qc = useQueryClient();
  const loc = useLocation();
  const badges: Record<string, number> = {
    inbox: me.stats.pending_proposals,
    studio: (me.studio.queued || 0) + (me.studio.running || 0),
  };
  const switchTo = (id: string) => {
    setActiveWardrobe(id === me.user.id ? "" : id);
    qc.clear();
    location.href = "/";
  };
  const current = activeWardrobe() || me.user.id;
  return (
    <div className="min-h-screen lg:pl-60">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-line bg-paper px-4 py-6 lg:flex">
        <NavLink to="/" className="mb-8 flex items-center gap-2.5 px-2">
          <img src="/favicon.svg" alt="" className="size-8" />
          <span className="font-display text-xl">Wardrobe</span>
        </NavLink>
        <nav className="flex flex-col gap-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                cx(
                  "flex h-10 items-center gap-3 rounded-xl px-3 text-sm transition-colors",
                  isActive ? "bg-ink text-paper" : "text-ink-2 hover:bg-canvas",
                )
              }
            >
              <n.icon className="size-[18px]" />
              <span className="flex-1">{n.label}</span>
              {n.badge && badges[n.badge] ? (
                <span className="min-w-5 rounded-full bg-accent px-1.5 text-center text-[11px] font-semibold leading-5 text-white">
                  {badges[n.badge]}
                </span>
              ) : null}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto space-y-3">
          {me.wardrobes.length > 1 && (
            <Select value={current} onChange={switchTo} options={me.wardrobes.map((w) => ({ value: w.owner_id, label: w.name }))} />
          )}
          <div className="rounded-2xl bg-canvas p-3 text-xs text-ink-2">
            <div className="flex justify-between">
              <span>Items</span>
              <b className="tabular-nums">{me.stats.items}</b>
            </div>
            <div className="mt-1 flex justify-between">
              <span>Photos</span>
              <b className="tabular-nums">{me.stats.photos}</b>
            </div>
            <div className="mt-1 flex justify-between">
              <span>AI pictures</span>
              <b className="tabular-nums">{me.stats.ai_photos}</b>
            </div>
          </div>
          <div className="flex items-center gap-2.5 px-1">
            {me.user.avatar_url ? (
              <img src={me.user.avatar_url} className="size-8 rounded-full" alt="" />
            ) : (
              <div className="grid size-8 place-items-center rounded-full bg-ink text-xs font-semibold text-paper">
                {me.user.name.slice(0, 1).toUpperCase()}
              </div>
            )}
            <div className="min-w-0 text-xs">
              <div className="truncate font-medium">{me.user.name}</div>
              <div className="truncate text-muted">{me.user.email}</div>
            </div>
          </div>
        </div>
      </aside>
      <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-line bg-paper/90 px-4 backdrop-blur lg:hidden">
        <NavLink to="/" className="flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="size-7" />
          <span className="font-display text-lg">Wardrobe</span>
        </NavLink>
        {!me.can_edit && <span className="text-xs text-muted">View only</span>}
      </header>
      {me.wardrobe !== me.user.id && (
        <div className="bg-accent-soft px-4 py-2 text-center text-xs text-accent">
          You're viewing {me.wardrobes.find((w) => w.owner_id === me.wardrobe)?.name}
          {!me.can_edit && " (view only)"} ·{" "}
          <button className="underline" onClick={() => switchTo(me.user.id)}>
            back to mine
          </button>
        </div>
      )}
      <main key={loc.pathname.split("/")[1]} className="pb-24 lg:pb-10">
        {children}
      </main>
      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-line bg-paper/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) => cx("relative flex h-16 flex-col items-center justify-center gap-1 text-[11px]", isActive ? "text-ink" : "text-muted")}
          >
            <n.icon className="size-5" />
            {n.label}
            {n.badge && badges[n.badge] ? (
              <span className="absolute right-[calc(50%-20px)] top-2 min-w-4 rounded-full bg-accent px-1 text-center text-[10px] font-semibold leading-4 text-white">
                {badges[n.badge]}
              </span>
            ) : null}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
