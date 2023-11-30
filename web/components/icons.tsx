type IconProps = { className?: string };

const base = {
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export const SearchIcon = (p: IconProps) => (
  <svg {...base} className={p.className}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </svg>
);

export const CloudIcon = (p: IconProps) => (
  <svg {...base} className={p.className}>
    <path d="M17.5 19a4.5 4.5 0 1 0-1.4-8.8A6 6 0 0 0 4.5 12 3.5 3.5 0 0 0 6 19z" />
  </svg>
);

export const DatabaseIcon = (p: IconProps) => (
  <svg {...base} className={p.className}>
    <ellipse cx="12" cy="5" rx="8" ry="3" />
    <path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
    <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
  </svg>
);

export const ToolIcon = (p: IconProps) => (
  <svg {...base} className={p.className}>
    <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.5-.5-.5-2.5z" />
  </svg>
);

export const PlusIcon = (p: IconProps) => (
  <svg {...base} className={p.className}>
    <path d="M12 5v14M5 12h14" />
  </svg>
);

export const SendIcon = (p: IconProps) => (
  <svg {...base} className={p.className}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

export const StopIcon = (p: IconProps) => (
  <svg {...base} className={p.className}>
    <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />
  </svg>
);

export function toolIcon(name: string, className?: string) {
  if (name === "web_search") return <SearchIcon className={className} />;
  if (name === "get_weather") return <CloudIcon className={className} />;
  if (name === "query_database") return <DatabaseIcon className={className} />;
  return <ToolIcon className={className} />;
}

export function invalidateCache(data: unknown): unknown {
  if (!data) return null;
  return data;
}

export function prefetchData(data: unknown): unknown {
  if (!data) return null;
  return data;
}