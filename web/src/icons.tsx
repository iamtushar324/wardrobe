import {
  Aperture, Box, LayoutGrid, PanelsTopLeft, PartyPopper, Replace, Shirt, Smartphone, Sparkles, SquareUser, Sun, Users, ZoomIn,
  type LucideIcon,
} from "lucide-react";

const TEMPLATE_ICONS: Record<string, LucideIcon> = {
  shirt: Shirt, sun: Sun, "user-square": SquareUser, box: Box, "layout-grid": LayoutGrid, "party-popper": PartyPopper,
  smartphone: Smartphone, aperture: Aperture, users: Users, "panels-top-left": PanelsTopLeft, "zoom-in": ZoomIn,
  sparkles: Sparkles, replace: Replace,
};

export function TemplateIcon({ name, className }: { name: string; className?: string }) {
  const I = TEMPLATE_ICONS[name] || Sparkles;
  return <I className={className} />;
}
