// Thin client for the wardrobe REST API (/api/v1). Cookie session + a CSRF header.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const WARDROBE_KEY = "wardrobe:active";

export function activeWardrobe(): string {
  return localStorage.getItem(WARDROBE_KEY) || "";
}

export function setActiveWardrobe(id: string) {
  if (id) localStorage.setItem(WARDROBE_KEY, id);
  else localStorage.removeItem(WARDROBE_KEY);
}

type Query = Record<string, string | number | boolean | undefined | null | string[]>;

function buildUrl(path: string, query?: Query): string {
  const url = new URL(path.startsWith("/api") ? path : "/api/v1" + path, location.origin);
  for (const [k, v] of Object.entries(query || {})) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    url.searchParams.set(k, Array.isArray(v) ? v.join(",") : String(v));
  }
  return url.pathname + url.search;
}

function headers(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = { "x-wardrobe-client": "web", ...extra };
  const w = activeWardrobe();
  if (w) h["x-wardrobe"] = w;
  return h;
}

async function parse(res: Response) {
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const detail = data?.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d: any) => d.msg).join(", ") : res.statusText;
    throw new ApiError(res.status, msg || `Request failed (${res.status})`);
  }
  return data;
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; query?: Query; form?: FormData } = {}): Promise<T> {
  const init: RequestInit = { method: opts.method || (opts.body || opts.form ? "POST" : "GET"), credentials: "same-origin" };
  if (opts.form) {
    init.body = opts.form;
    init.headers = headers();
  } else if (opts.body !== undefined) {
    init.body = JSON.stringify(opts.body);
    init.headers = headers({ "Content-Type": "application/json" });
  } else {
    init.headers = headers();
  }
  return parse(await fetch(buildUrl(path, opts.query), init));
}

/** multipart upload with progress (fetch has no upload progress) */
export function uploadForm<T = any>(path: string, form: FormData, onProgress?: (loaded: number, total: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", buildUrl(path));
    for (const [k, v] of Object.entries(headers())) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => onProgress?.(e.loaded, e.total);
    xhr.onload = () => {
      let data: any = null;
      try {
        data = JSON.parse(xhr.responseText || "null");
      } catch {
        data = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new ApiError(xhr.status, data?.detail || `Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new ApiError(0, "Network error during upload"));
    xhr.send(form);
  });
}

// ---------------- types ----------------
export type Img = { sha: string; sm: string; md: string; lg: string; full: string; cutout?: boolean; ai?: boolean; link_id?: string };
export type Color = { name: string; hex: string; share: number | null };

export type Item = {
  id: string;
  owner_id: string;
  name: string;
  category: string | null;
  subcategory: string | null;
  pattern: string | null;
  material: string | null;
  fit: string | null;
  size: string | null;
  size_system: string | null;
  brand: string | null;
  status: string;
  location: string | null;
  notes: string | null;
  store: string | null;
  store_url: string | null;
  purchase_date: string | null;
  currency: string | null;
  gifted_by: string | null;
  price: number | null;
  original_price: number | null;
  formality: number | null;
  favorite: boolean;
  wear_count: number;
  last_worn_at: number | null;
  created_at: number;
  updated_at: number;
  created_by: string | null;
  colors: Color[];
  seasons: string[];
  occasions: string[];
  styles: string[];
  tags: string[];
  provenance: Record<string, string>;
  cover: Img | null;
  photo_count?: number;
  worn_count_photos?: number;
  ai_count?: number;
  photos?: ItemPhoto[];
};

export type ItemPhoto = {
  link_id: string;
  role: string;
  bbox: number[] | null;
  confidence: number | null;
  confirmed: boolean;
  photo: { id: string; kind: string; ai: boolean; template: string | null; width: number; height: number; taken_at: number | null; created_at: number; source: string; image: Img };
  crop: Img | null;
  cutout: Img | null;
};

export type PhotoLink = {
  id: string;
  item_id: string;
  role: string;
  bbox: number[] | null;
  confidence: number | null;
  confirmed: boolean;
  crop: Img | null;
  cutout: Img | null;
  item: { id: string; name: string; category: string | null } | null;
};

export type Photo = {
  id: string;
  kind: string;
  source: string;
  ai: boolean;
  template: string | null;
  gen_job_id: string | null;
  width: number;
  height: number;
  taken_at: number | null;
  filename: string | null;
  note: string | null;
  batch_id: string | null;
  status: string;
  error: string | null;
  created_at: number;
  created_by: string | null;
  image: Img;
  links?: PhotoLink[];
  people?: string[];
  analysis?: any;
};

export type Facet = { value: string; count: number };
export type Facets = Record<string, Facet[]>;

export type Taxonomy = {
  categories: Record<string, string[]>;
  seasons: string[];
  occasions: string[];
  patterns: string[];
  materials: string[];
  fits: string[];
  statuses: string[];
  photo_kinds: string[];
  link_roles: string[];
  palette: Record<string, string>;
};

export type User = { id: string; email: string; name: string; avatar_url: string | null; role: string; status: string };

export type Me = {
  user: User;
  via: string;
  wardrobe: string;
  can_edit: boolean;
  wardrobes: { owner_id: string; name: string; can_edit: boolean }[];
  stats: { items: number; photos: number; ai_photos: number; pending_proposals: number; paid_total: number; mrp_total: number };
  studio: Record<string, number>;
  vision: boolean;
  taxonomy: Taxonomy;
};

export type Config = {
  site_name: string;
  auth_modes: string[];
  signed_in: boolean;
  public_url: string;
  clerk?: { publishable_key: string; frontend_api: string };
  chatgpt_available: boolean;
};

export type Batch = {
  id: string;
  note: string | null;
  hints: Record<string, any>;
  auto_commit: string;
  analyze: boolean;
  status: string;
  message: string | null;
  created_by: string | null;
  created_at: number;
  updated_at: number;
  photo_counts: Record<string, number>;
  photos: number;
  proposal_counts: Record<string, number>;
  cover: string | null;
};

export type ProposalLink = {
  photo_id: string;
  role: string;
  bbox: number[] | null;
  crop_sha?: string | null;
  cutout_sha?: string | null;
  confidence?: number | null;
  photo: Img | null;
  kind: string | null;
  crop: Img | null;
  cutout: Img | null;
};

export type Proposal = {
  id: string;
  batch_id: string;
  status: string;
  data: Record<string, any>;
  links: ProposalLink[];
  match: { id: string; name: string; cover: Img | null } | null;
  confidence: number | null;
  reason: string | null;
  item_id: string | null;
  preview: Img | null;
};

export type BatchView = {
  batch: Batch;
  photos: (Photo & { analysis: { kind: string; summary: string; items: number; tag: any; receipt: any } | null; assigned: boolean })[];
  proposals: Proposal[];
};

export type Template = {
  id: string;
  name: string;
  icon: string;
  needs_person: boolean;
  multi_item: boolean;
  aspect: string;
  group: string;
  description: string;
  prompt: string;
  custom?: boolean;
  auto?: boolean;
  done?: number;
};

export type Job = {
  id: string;
  template: string;
  person_photo_id: string | null;
  engine: string;
  source: string;
  status: string;
  priority: number;
  attempts: number;
  note: string | null;
  error: string | null;
  result_photo_id: string | null;
  account_email: string | null;
  duration_s: number | null;
  cost_usd: number | null;
  created_at: number;
  claimed_at: number | null;
  finished_at: number | null;
  item_ids: string[];
  prompt: string;
  items?: { id: string; name: string; cover: Img | null }[];
  result?: Img | null;
  position?: number;
  elapsed_s?: number;
};

export type Limits = {
  plan?: string;
  reached?: string | null;
  primary?: { used_percent: number | null; window_minutes: number | null; resets_at: number | null } | null;
  secondary?: { used_percent: number | null; window_minutes: number | null; resets_at: number | null } | null;
  credits?: { has_credits?: boolean; unlimited?: boolean; balance?: string | null };
};

export type Account = {
  status: string;
  email?: string | null;
  plan?: string | null;
  limits?: Limits;
  limits_at?: number | null;
  message?: string | null;
  connected_at?: number | null;
};

export type StudioPrefs = {
  paused: boolean;
  auto_mode: boolean;
  auto_templates: string[];
  model_photo_ids: string[];
  daily_cap: number;
  engine: string;
  fallback_openrouter: boolean;
  openrouter_daily_cap: number;
  min_interval_s: number;
};

export type Studio = {
  prefs: StudioPrefs;
  templates: Template[];
  jobs: Job[];
  counts: Record<string, number>;
  available: boolean;
  reason: string;
  worker: { online: boolean; last_seen?: number; state?: string; message?: string; host?: string; codex_version?: string };
  account: Account;
  usage: {
    chatgpt_today: number;
    daily_cap: number;
    openrouter_today: number;
    openrouter_daily_cap: number;
    openrouter_cost_today: number;
    week: number;
    total: number;
    avg_seconds: number | null;
    openrouter_configured: boolean;
  };
  model_photos: { id: string; image: Img }[];
  warnings: string[];
};

export type LoginState = {
  id: string;
  kind: string;
  status: string;
  verification_url: string | null;
  user_code: string | null;
  email: string | null;
  message: string | null;
  expires_at: number;
};
