"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

/* ---------- data shapes (data/out/models.json) ---------- */
type Pt = { m: string; lab: string; org: string; d: string; s: number; n: number; open: boolean | null };
type Bench = {
  id: string; name: string; gloss: string; released: string | null;
  baseline: number; ceiling: number; points: Pt[]; frontier: Pt[];
};
type Direction = { id: string; label: string; blurb: string; benchmarks: Bench[] };
type Eci = { m: string; lab: string; org: string; country: string; d: string; v: number; lo: number | null; hi: number | null; open: boolean };
type Hz = { m: string; lab: string; org: string; d: string; min: number; lo: number | null; hi: number | null };
type Release = { m: string; lab: string; org: string; d: string; domains: string[]; open: boolean | null; frontier: boolean; link: string | null };
export type Models = {
  generated: string;
  source: { name: string; license: string; url: string; citation: string; retrieved: string | null };
  labs: { id: string; name: string }[];
  directions: Direction[];
  eci: Eci[];
  horizon: Hz[];
  releases: Release[];
};

/* ---------- palette: fixed lab order, validated on the dark surface ---------- */
const LAB: Record<string, string> = {
  openai: "#3987e5", anthropic: "#d95926", google: "#199e70", meta: "#c98500",
  xai: "#d55181", deepseek: "#008300", alibaba: "#9085e9", mistral: "#e66767",
  other: "#5f7384",
};
const INK = "#e6eef5", INK2 = "#9fb3c4", MUTED = "#5f7384", GRID = "#14222f", PANEL = "#070d15";
const SEQ: [number, number, number][] = [[13, 33, 53], [42, 111, 192], [191, 224, 255]];
function seq(n: number) {
  const t = Math.max(0, Math.min(1, n)) * 2, i = t >= 1 ? 1 : 0, f = t - i;
  const c = SEQ[i].map((a, k) => Math.round(a + (SEQ[i + 1][k] - a) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

/* ---------- helpers ---------- */
const T = (d: string) => Date.parse(d + "T00:00:00Z");
const lin = (d0: number, d1: number, r0: number, r1: number) => (v: number) => Math.round((r0 + ((v - d0) / (d1 - d0)) * (r1 - r0)) * 10) / 10;
const pct = (s: number) => `${Math.round(s * 100)}%`;
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fmtDate = (d: string) => `${MON[+d.slice(5, 7) - 1]} ${d.slice(0, 4)}`;
function fmtMin(m: number) {
  if (m < 1) return `${Math.round(m * 60)} sec`;
  if (m < 60) return `${Math.round(m)} min`;
  if (m < 1440) return `${(m / 60).toFixed(m < 600 ? 1 : 0)} hr`;
  return `${(m / 1440).toFixed(1)} days`;
}
function months(from: string, to: string) {
  const out: string[] = [];
  let y = +from.slice(0, 4), m = +from.slice(5, 7);
  const ty = +to.slice(0, 4), tm = +to.slice(5, 7);
  while (y < ty || (y === ty && m <= tm)) {
    out.push(`${y}-${String(m).padStart(2, "0")}`);
    if (++m > 12) { m = 1; y++; }
  }
  return out;
}
function yearsBetween(a: number, b: number) {
  const out: number[] = [];
  for (let y = new Date(a).getUTCFullYear() + 1; y <= new Date(b).getUTCFullYear(); y++) out.push(y);
  return out;
}
function useWidth<E extends HTMLElement>(): [React.RefObject<E | null>, number] {
  const ref = useRef<E | null>(null);
  const [w, setW] = useState(1080);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(320, Math.floor(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

type Tip = { x: number; y: number; title: string; rows: [string, string][]; lab?: string } | null;
type Ctx = { cutoff: string; focus: string | null; setTip: (t: Tip) => void; labName: (id: string) => string };

const dim = (focus: string | null, lab: string) => (focus && focus !== lab ? 0.1 : 0.92);

function Section({ title, sub, children, note }: { title: string; sub: string; children: ReactNode; note?: string }) {
  return (
    <section className="mt-14">
      <h2 className="text-[22px] font-bold tracking-tight text-slate-100">{title}</h2>
      <p className="mt-1 max-w-3xl text-[14px] leading-relaxed text-slate-400">{sub}</p>
      <div className="mt-5">{children}</div>
      {note && <p className="mt-3 max-w-3xl text-[12px] leading-relaxed text-slate-500">{note}</p>}
    </section>
  );
}

function YearAxis({ x, t0, t1, y0, y1, short }: { x: (v: number) => number; t0: number; t1: number; y0: number; y1: number; short?: boolean }) {
  return (
    <g>
      {yearsBetween(t0, t1).map((y) => {
        const px = x(Date.UTC(y, 0, 1));
        return (
          <g key={y}>
            <line x1={px} x2={px} y1={y0} y2={y1} stroke={GRID} />
            <text x={px + 3} y={y1 + 14} fill={MUTED} fontSize={11}>{short ? `'${String(y).slice(2)}` : y}</text>
          </g>
        );
      })}
    </g>
  );
}

/* ---------- 1. saturation heat strip ---------- */
function Saturation({ directions, ctx, end }: { directions: Direction[]; ctx: Ctx; end: string }) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const narrow = W < 720;
  const L = narrow ? 118 : 190, R = narrow ? 44 : 210, ROW = 19, HEAD = 26;
  const t0 = T("2019-06-01"), t1 = T(end), tc = Math.min(T(ctx.cutoff), t1);
  const x = lin(t0, t1, L, W - R);
  let y = 18;
  const rows: { b: Bench; y: number }[] = [], heads: { d: Direction; y: number }[] = [];
  for (const d of directions) {
    heads.push({ d, y: y + 16 });
    y += HEAD;
    for (const b of d.benchmarks) { rows.push({ b, y }); y += ROW; }
    y += 8;
  }
  const H = y + 22;
  return (
    <div ref={ref} className="relative w-full overflow-hidden">
      <svg width={W} height={H} role="img" aria-label="Best score on each benchmark over time">
        <YearAxis x={x} t0={t0} t1={t1} y0={0} y1={H - 22} short={narrow} />
        {yearsBetween(t0, t1).map((yr) => (
          <text key={yr} x={x(Date.UTC(yr, 0, 1)) + 3} y={10} fill={MUTED} fontSize={11}>{narrow ? `'${String(yr).slice(2)}` : yr}</text>
        ))}
        {heads.map(({ d, y }) => (
          <text key={d.id} x={0} y={y} fill={INK} fontSize={12} fontWeight={700} letterSpacing={0.6}>
            {d.label.toUpperCase()}
          </text>
        ))}
        {rows.map(({ b, y }) => {
          const f = b.frontier.filter((p) => p.d <= ctx.cutoff);
          const cur = f[f.length - 1];
          return (
            <g key={b.id}>
              <text x={L - 8} y={y + 13} textAnchor="end" fill={cur ? INK2 : MUTED} fontSize={11.5}>
                {narrow && b.name.length > 17 ? b.name.slice(0, 16) + "…" : b.name}
              </text>
              <rect x={L} y={y + 1} width={W - R - L} height={ROW - 3} fill="#0a141e" rx={2} />
              {f.map((p, i) => {
                const xa = Math.max(L, x(T(p.d)));
                const xb = x(i + 1 < f.length ? T(f[i + 1].d) : tc);
                if (xb <= xa) return null;
                return (
                  <rect key={i} x={xa} y={y + 1} width={xb - xa} height={ROW - 3} fill={seq(p.n)}
                    onMouseMove={(e) => ctx.setTip({
                      x: e.clientX, y: e.clientY, title: b.name, lab: p.lab,
                      rows: [["Best so far", pct(p.s)], ["Model", p.m], ["Lab", p.org], ["Since", fmtDate(p.d)], ["Measures", b.gloss]],
                    })}
                    onMouseLeave={() => ctx.setTip(null)} />
                );
              })}
              {cur && (
                <text x={W - R + 8} y={y + 13} fill={INK2} fontSize={11.5}>
                  <tspan fill={INK} fontWeight={600}>{pct(cur.s)}</tspan>
                  {!narrow && <tspan dx={8} fill={MUTED}>{cur.m}</tspan>}
                </text>
              )}
            </g>
          );
        })}
        {tc < t1 && <line x1={x(tc)} x2={x(tc)} y1={0} y2={H - 22} stroke={INK2} strokeDasharray="3 3" />}
      </svg>
      <div className="mt-1 flex items-center gap-3 text-[11px] text-slate-400">
        <span>Share of the benchmark solved by the best model</span>
        <span>0%</span>
        <span className="h-2.5 w-40 rounded-sm" style={{ background: `linear-gradient(90deg, ${seq(0)}, ${seq(0.5)}, ${seq(1)})` }} />
        <span>100%</span>
      </div>
    </div>
  );
}

/* ---------- 2. capability index race ---------- */
function Race({ eci, ctx, end }: { eci: Eci[]; ctx: Ctx; end: string }) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const H = 430, L = 44, R = 20, TOP = 16, B = 30;
  const t0 = T("2023-01-01"), t1 = T(end);
  const x = lin(t0, t1, L, W - R), y = lin(82, 172, H - B, TOP);
  const vis = eci.filter((p) => p.d <= ctx.cutoff);
  const rec: Eci[] = [];
  for (const p of vis) if (!rec.length || p.v > rec[rec.length - 1].v) rec.push(p);
  let path = "";
  rec.forEach((p, i) => { path += i ? `H${x(T(p.d))}V${y(p.v)}` : `M${x(T(p.d))},${y(p.v)}`; });
  if (rec.length) path += `H${x(Math.min(T(ctx.cutoff), t1))}`;
  let lx = -1e9, ly = 1e9;
  const labelled = rec.filter((p) => {
    const px = x(T(p.d)), py = y(p.v);
    if (px - lx > 84 || ly - py > 15) { lx = px; ly = py; return true; }
    return false;
  });
  return (
    <div ref={ref} className="relative w-full overflow-hidden">
      <svg width={W} height={H} role="img" aria-label="Epoch Capabilities Index by model release date">
        {[100, 120, 140, 160].map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke={GRID} />
            <text x={L - 8} y={y(v) + 4} textAnchor="end" fill={MUTED} fontSize={11}>{v}</text>
          </g>
        ))}
        <YearAxis x={x} t0={t0} t1={t1} y0={TOP} y1={H - B} short={W < 620} />
        {!vis.length && (
          <text x={(L + W - R) / 2} y={H / 2} textAnchor="middle" fill={MUTED} fontSize={14}>
            The index starts with models released in 2023. Scrub forward.
          </text>
        )}
        <path d={path} fill="none" stroke={INK} strokeWidth={2} opacity={ctx.focus ? 0.25 : 0.9} />
        {vis.map((p, i) => (
          <g key={i} opacity={dim(ctx.focus, p.lab)}>
            <circle cx={x(T(p.d))} cy={y(p.v)} r={p.open ? 3.5 : 4.5} fill={p.open ? PANEL : LAB[p.lab]}
              stroke={LAB[p.lab]} strokeWidth={p.open ? 2 : 0} />
            <circle cx={x(T(p.d))} cy={y(p.v)} r={10} fill="transparent"
              onMouseMove={(e) => ctx.setTip({
                x: e.clientX, y: e.clientY, title: p.m, lab: p.lab,
                rows: [["Index", p.v.toFixed(1)], ["Lab", p.org || "—"], ["Released", fmtDate(p.d)], ["Weights", p.open ? "Open" : "Closed"]],
              })}
              onMouseLeave={() => ctx.setTip(null)} />
          </g>
        ))}
        {!ctx.focus && labelled.map((p) => (
          <text key={p.m} x={x(T(p.d)) - 8} y={y(p.v) - 7} textAnchor="end" fill={INK} fontSize={11.5} fontWeight={600}
            style={{ paintOrder: "stroke", stroke: "#03070c", strokeWidth: 4 }}>{p.m}</text>
        ))}
      </svg>
      <div className="mt-1 flex flex-wrap items-center gap-x-5 gap-y-1 text-[11px] text-slate-400">
        <span className="flex items-center gap-1.5"><i className="inline-block h-2.5 w-2.5 rounded-full bg-slate-400" /> closed weights</span>
        <span className="flex items-center gap-1.5"><i className="inline-block h-2.5 w-2.5 rounded-full border-2 border-slate-400" /> open weights</span>
        <span className="flex items-center gap-1.5"><i className="inline-block h-0.5 w-5 bg-slate-200" /> best model so far</span>
      </div>
    </div>
  );
}

/* ---------- 3. small multiples per direction ---------- */
function Panel({ b, ctx, t0, t1, w }: { b: Bench; ctx: Ctx; t0: number; t1: number; w: number }) {
  const H = 190, L = 34, R = 10, TOP = 12, B = 24;
  const x = lin(t0, t1, L, w - R), y = lin(0, 1, H - B, TOP);
  const vis = b.points.filter((p) => p.d <= ctx.cutoff);
  const f = b.frontier.filter((p) => p.d <= ctx.cutoff);
  const cur = f[f.length - 1];
  let path = "";
  f.forEach((p, i) => { path += i ? `H${x(T(p.d))}V${y(p.s)}` : `M${x(T(p.d))},${y(p.s)}`; });
  if (f.length) path += `H${x(Math.min(T(ctx.cutoff), t1))}`;
  return (
    <div className="rounded-lg border border-slate-800 bg-[#070d15] p-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-[14px] font-semibold text-slate-100">{b.name}</h3>
        <span className="shrink-0 text-[13px] font-semibold tabular-nums text-slate-100">{cur ? pct(cur.s) : "—"}</span>
      </div>
      <div className="flex items-baseline justify-between gap-2 text-[11.5px] text-slate-500">
        <span className="truncate">{b.gloss}</span>
        <span className="shrink-0">{cur?.m ?? "not yet attempted"}</span>
      </div>
      <svg width={w} height={H} className="mt-1" role="img" aria-label={`${b.name} scores over time`}>
        {[0, 0.5, 1].map((v) => (
          <g key={v}>
            <line x1={L} x2={w - R} y1={y(v)} y2={y(v)} stroke={GRID} />
            <text x={L - 6} y={y(v) + 4} textAnchor="end" fill={MUTED} fontSize={10}>{pct(v)}</text>
          </g>
        ))}
        {b.baseline > 0 && (
          <line x1={L} x2={w - R} y1={y(b.baseline)} y2={y(b.baseline)} stroke={MUTED} strokeDasharray="2 4">
            <title>Chance level</title>
          </line>
        )}
        {yearsBetween(t0, t1).map((yr) => (
          <text key={yr} x={x(Date.UTC(yr, 0, 1))} y={H - 8} fill={MUTED} fontSize={10} textAnchor="middle">
            {w < 300 ? `'${String(yr).slice(2)}` : yr}
          </text>
        ))}
        <path d={path} fill="none" stroke={INK} strokeWidth={1.5} opacity={ctx.focus ? 0.2 : 0.75} />
        {vis.map((p, i) => (
          <g key={i} opacity={dim(ctx.focus, p.lab) * 0.9}>
            <circle cx={x(T(p.d))} cy={y(p.s)} r={3} fill={LAB[p.lab]} />
            <circle cx={x(T(p.d))} cy={y(p.s)} r={8} fill="transparent"
              onMouseMove={(e) => ctx.setTip({
                x: e.clientX, y: e.clientY, title: p.m, lab: p.lab,
                rows: [[b.name, pct(p.s)], ["Lab", p.org || "—"], ["Released", fmtDate(p.d)]],
              })}
              onMouseLeave={() => ctx.setTip(null)} />
          </g>
        ))}
      </svg>
    </div>
  );
}

function Directions({ directions, ctx, end }: { directions: Direction[]; ctx: Ctx; end: string }) {
  const [id, setId] = useState("coding");
  const [ref, W] = useWidth<HTMLDivElement>();
  const d = directions.find((x) => x.id === id) ?? directions[0];
  const cols = W >= 960 ? 3 : W >= 620 ? 2 : 1;
  const w = Math.floor((W - (cols - 1) * 14) / cols) - 26;
  const first = d.benchmarks.reduce((a, b) => (b.points[0] && b.points[0].d < a ? b.points[0].d : a), end);
  const t0 = T(first.slice(0, 4) + "-01-01"), t1 = T(end);
  return (
    <div ref={ref} className="w-full overflow-hidden">
      <div className="flex flex-wrap gap-2">
        {directions.map((x) => (
          <button key={x.id} onClick={() => setId(x.id)}
            className={`rounded-full border px-3.5 py-1.5 text-[13px] font-medium transition ${
              x.id === d.id ? "border-sky-400 bg-sky-400/15 text-sky-100" : "border-slate-700 text-slate-400 hover:text-slate-200"}`}>
            {x.label}
          </button>
        ))}
      </div>
      <p className="mt-3 text-[13px] text-slate-400">{d.blurb}</p>
      <div className="mt-4 grid gap-3.5" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
        {d.benchmarks.map((b) => <Panel key={b.id} b={b} ctx={ctx} t0={t0} t1={t1} w={w} />)}
      </div>
    </div>
  );
}

/* ---------- 4. task horizon ---------- */
function Horizon({ data, ctx, end }: { data: Hz[]; ctx: Ctx; end: string }) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const H = 380, L = 84, R = 20, TOP = 16, B = 30;
  const t0 = T("2019-01-01"), t1 = T(end);
  const x = lin(t0, t1, L, W - R);
  const ly = lin(Math.log10(0.03), Math.log10(2880), H - B, TOP);
  const y = (m: number) => ly(Math.log10(m));
  const vis = data.filter((p) => p.d <= ctx.cutoff);
  const rec: Hz[] = [];
  for (const p of vis) if (!rec.length || p.min > rec[rec.length - 1].min) rec.push(p);
  let path = "";
  rec.forEach((p, i) => { path += `${i ? "L" : "M"}${x(T(p.d))},${y(p.min)}`; });
  const ticks: [number, string][] = [[0.0667, "4 sec"], [1, "1 min"], [15, "15 min"], [60, "1 hour"], [480, "8 hours"], [2400, "1 work week"]];
  return (
    <div ref={ref} className="w-full overflow-hidden">
      <svg width={W} height={H} role="img" aria-label="Length of task models complete half the time, by release date">
        {ticks.map(([v, l]) => (
          <g key={l}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke={GRID} />
            <text x={L - 8} y={y(v) + 4} textAnchor="end" fill={MUTED} fontSize={11}>{l}</text>
          </g>
        ))}
        <YearAxis x={x} t0={t0} t1={t1} y0={TOP} y1={H - B} short={W < 620} />
        <path d={path} fill="none" stroke={INK} strokeWidth={2} opacity={ctx.focus ? 0.25 : 0.85} />
        {vis.map((p, i) => (
          <g key={i} opacity={dim(ctx.focus, p.lab)}>
            {p.lo != null && p.hi != null && (
              <line x1={x(T(p.d))} x2={x(T(p.d))} y1={y(Math.max(p.lo, 0.03))} y2={y(Math.min(p.hi, 2880))}
                stroke={LAB[p.lab]} strokeWidth={1} opacity={0.45} />
            )}
            <circle cx={x(T(p.d))} cy={y(p.min)} r={4.5} fill={LAB[p.lab]} stroke="#03070c" strokeWidth={1.5} />
            <circle cx={x(T(p.d))} cy={y(p.min)} r={11} fill="transparent"
              onMouseMove={(e) => ctx.setTip({
                x: e.clientX, y: e.clientY, title: p.m, lab: p.lab,
                rows: [["Task length", fmtMin(p.min)],
                  ["95% range", p.lo != null && p.hi != null ? `${fmtMin(p.lo)} to ${fmtMin(p.hi)}` : "—"],
                  ["Lab", p.org], ["Released", fmtDate(p.d)]],
              })}
              onMouseLeave={() => ctx.setTip(null)} />
          </g>
        ))}
        {!ctx.focus && rec.slice(-1).map((p) => (
          <text key={p.m} x={x(T(p.d)) - 10} y={y(p.min) - 8} textAnchor="end" fill={INK} fontSize={12} fontWeight={600}
            style={{ paintOrder: "stroke", stroke: "#03070c", strokeWidth: 4 }}>{p.m} · {fmtMin(p.min)}</text>
        ))}
      </svg>
    </div>
  );
}

/* ---------- 5. modality matrix ---------- */
const DOMAINS = ["Language", "Vision", "Multimodal", "Image generation", "Video", "Speech", "Audio", "Biology", "Games", "Robotics"];
function Modalities({ releases, ctx, end }: { releases: Release[]; ctx: Ctx; end: string }) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const years = useMemo(() => { const o: number[] = []; for (let y = 2017; y <= +end.slice(0, 4); y++) o.push(y); return o; }, [end]);
  const { grid, max } = useMemo(() => {
    const g: Record<string, Record<number, Release[]>> = {};
    let mx = 1;
    for (const r of releases) {
      if (r.d > ctx.cutoff || (ctx.focus && r.lab !== ctx.focus)) continue;
      for (const dm of r.domains) {
        if (!DOMAINS.includes(dm)) continue;
        const cell = ((g[dm] ??= {})[+r.d.slice(0, 4)] ??= []);
        cell.push(r);
        mx = Math.max(mx, cell.length);
      }
    }
    return { grid: g, max: mx };
  }, [releases, ctx.cutoff, ctx.focus]);
  const L = W < 620 ? 96 : 130, ROW = 34, TOP = 22;
  const cw = (W - L) / years.length;
  return (
    <div ref={ref} className="w-full overflow-hidden">
      <svg width={W} height={TOP + DOMAINS.length * ROW + 4} role="img" aria-label="Notable models released per year by modality">
        {years.map((yr, j) => (
          <text key={yr} x={L + j * cw + cw / 2} y={14} textAnchor="middle" fill={MUTED} fontSize={11}>{yr}</text>
        ))}
        {DOMAINS.map((dm, i) => (
          <g key={dm}>
            <text x={L - 10} y={TOP + i * ROW + 21} textAnchor="end" fill={INK2} fontSize={12}>{dm}</text>
            {years.map((yr, j) => {
              const cell = grid[dm]?.[yr] ?? [];
              const n = cell.length, t = n / max;
              return (
                <g key={yr}
                  onMouseMove={(e) => n && ctx.setTip({
                    x: e.clientX, y: e.clientY, title: `${dm} · ${yr}`,
                    rows: [["Notable models", String(n)], ...cell.slice(-5).reverse().map((r): [string, string] => [r.org || "—", r.m])],
                  })}
                  onMouseLeave={() => ctx.setTip(null)}>
                  <rect x={L + j * cw + 1} y={TOP + i * ROW + 1} width={cw - 2} height={ROW - 2} rx={3}
                    fill={n ? seq(0.12 + 0.88 * Math.sqrt(t)) : "#0a141e"} />
                  {n > 0 && cw > 30 && (
                    <text x={L + j * cw + cw / 2} y={TOP + i * ROW + 21} textAnchor="middle" fontSize={12} fontWeight={600}
                      fill={Math.sqrt(t) > 0.62 ? "#06121d" : INK}>{n}</text>
                  )}
                </g>
              );
            })}
          </g>
        ))}
      </svg>
    </div>
  );
}

/* ---------- page ---------- */
export default function ModelTrack({ data }: { data: Models }) {
  const end = useMemo(() => {
    const last = data.eci.reduce((a, p) => (p.d > a ? p.d : a), data.generated);
    return last.slice(0, 7) + "-" + String(new Date(Date.UTC(+last.slice(0, 4), +last.slice(5, 7), 0)).getUTCDate());
  }, [data]);
  const ms = useMemo(() => months("2017-01", end), [end]);
  const [i, setI] = useState(ms.length - 1);
  const [playing, setPlaying] = useState(false);
  const [focus, setFocus] = useState<string | null>(null);
  const [tip, setTip] = useState<Tip>(null);

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => setI((v) => {
      if (v >= ms.length - 1) { setPlaying(false); return v; }
      return v + 1;
    }), 110);
    return () => clearInterval(id);
  }, [playing, ms.length]);

  const cutoff = `${ms[i]}-31`;
  const labName = (id: string) => data.labs.find((l) => l.id === id)?.name ?? id;
  const ctx: Ctx = { cutoff, focus, setTip, labName };

  const stats = useMemo(() => {
    const top = data.eci.filter((p) => p.d <= cutoff).reduce<Eci | null>((a, p) => (!a || p.v > a.v ? p : a), null);
    const all = data.directions.flatMap((d) => d.benchmarks);
    const live = all.filter((b) => b.frontier[0] && b.frontier[0].d <= cutoff);
    const solved = live.filter((b) => b.frontier.filter((p) => p.d <= cutoff).slice(-1)[0].n >= 0.9);
    const hz = data.horizon.filter((p) => p.d <= cutoff).reduce<Hz | null>((a, p) => (!a || p.min > a.min) ? p : a, null);
    const rel = data.releases.filter((r) => r.d <= cutoff);
    return { top, live: live.length, solved: solved.length, hz, rel: rel.length, latest: rel.filter((r) => r.frontier || r.lab !== "other").slice(-5).reverse() };
  }, [data, cutoff]);

  const tiles: [string, string, string][] = [
    ["Most capable model", stats.top?.m ?? "—", stats.top ? `${stats.top.org} · index ${stats.top.v.toFixed(0)}` : "index starts in 2023"],
    ["Benchmarks 90% solved", `${stats.solved} of ${stats.live}`, "of those with a recorded score"],
    ["Longest task done half the time", stats.hz ? fmtMin(stats.hz.min) : "—", stats.hz ? stats.hz.m : "no measurement yet"],
    ["Notable models released", stats.rel.toLocaleString(), "since January 2017"],
  ];

  return (
    <div className="min-h-screen w-full min-w-0 bg-[#03070c] text-slate-200"
      style={{ backgroundImage: "linear-gradient(#0a1622 1px, transparent 1px), linear-gradient(90deg, #0a1622 1px, transparent 1px)", backgroundSize: "44px 44px" }}>
      {/* sticky time bar */}
      <div className="sticky top-0 z-30 border-b border-slate-800 bg-[#03070c]/92 backdrop-blur">
        <div className="mx-auto flex max-w-[1180px] flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3 sm:px-6">
          <nav className="flex items-center gap-1 text-[13px] font-semibold">
            <Link href="/" className="rounded-full px-3 py-1.5 text-slate-400 hover:text-slate-100">People</Link>
            <span className="rounded-full bg-sky-400/15 px-3 py-1.5 text-sky-100">Models</span>
          </nav>
          <button onClick={() => { if (i >= ms.length - 1) setI(0); setPlaying((p) => !p); }}
            className="rounded-full border border-sky-400/60 px-4 py-1.5 text-[13px] font-semibold text-sky-100 hover:bg-sky-400/15">
            {playing ? "Pause" : i >= ms.length - 1 ? "Replay 2017 → now" : "Play"}
          </button>
          <div className="flex min-w-[220px] flex-1 items-center gap-3">
            <input type="range" min={0} max={ms.length - 1} value={i} aria-label="Month"
              onChange={(e) => { setPlaying(false); setI(+e.target.value); }}
              className="h-1 w-full cursor-pointer accent-sky-400" />
            <span className="w-[84px] shrink-0 text-right text-[15px] font-bold tabular-nums text-slate-100">{fmtDate(ms[i] + "-01")}</span>
          </div>
        </div>
        <div className="mx-auto flex max-w-[1180px] items-center gap-x-1 overflow-x-auto whitespace-nowrap px-4 pb-2.5 sm:px-6 [scrollbar-width:none]">
          {data.labs.map((l) => (
            <button key={l.id} onClick={() => setFocus(focus === l.id ? null : l.id)}
              className={`flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] transition ${
                focus === l.id ? "bg-slate-700/70 text-slate-50" : focus ? "text-slate-600" : "text-slate-300 hover:bg-slate-800"}`}>
              <i className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: LAB[l.id], opacity: focus && focus !== l.id ? 0.35 : 1 }} />
              {l.name}
            </button>
          ))}
          {focus && <button onClick={() => setFocus(null)} className="px-2 text-[12px] text-sky-300 hover:underline">show all</button>}
        </div>
      </div>

      <main className="mx-auto max-w-[1180px] px-4 pb-24 sm:px-6">
        <header className="pt-10">
          <h1 className="text-[34px] font-extrabold leading-tight tracking-tight text-slate-50 sm:text-[42px]">
            How fast the models moved
          </h1>
          <p className="mt-3 max-w-3xl text-[15px] leading-relaxed text-slate-400">
            Every score here is a recorded result for a named model on a named benchmark. Drag the
            month above, or press play, to watch the frontier move from 2017 to today. Click a lab to isolate it.
          </p>
        </header>

        <div className="mt-8 grid grid-cols-2 gap-3 lg:grid-cols-4">
          {tiles.map(([k, v, s]) => (
            <div key={k} className="rounded-lg border border-slate-800 bg-[#070d15] p-4">
              <div className="text-[12px] text-slate-400">{k}</div>
              <div className="mt-1 truncate text-[22px] font-bold tabular-nums text-slate-50">{v}</div>
              <div className="mt-0.5 truncate text-[12px] text-slate-500">{s}</div>
            </div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-[12.5px] text-slate-400">
          <span className="font-semibold text-slate-300">Just released</span>
          {stats.latest.map((r) => (
            <span key={r.m + r.d} className="flex items-center gap-1.5">
              <i className="inline-block h-2 w-2 rounded-full" style={{ background: LAB[r.lab] }} />
              {r.m} <span className="text-slate-600">{fmtDate(r.d)}</span>
            </span>
          ))}
        </div>

        <Section title="Every benchmark gets beaten"
          sub="One row per benchmark. A row lights up as the best available model solves more of it. New benchmarks keep appearing at the bottom of each group because the old ones stop being hard."
          note="Brightness is the best score to date, rescaled between chance level and the benchmark's maximum. Models are placed at their release date, so a row can start before the benchmark itself was published: older models were tested after the fact.">
          <Saturation directions={data.directions} ctx={ctx} end={end} />
        </Section>

        <Section title="The race at the frontier"
          sub="One dot per model, placed by release date and by Epoch's Capabilities Index, which merges results from dozens of benchmarks into a single score. The white line is the best model available at each moment."
          note="The index begins in 2023 because earlier models share too few benchmarks with current ones to be put on one scale.">
          <Race eci={data.eci} ctx={ctx} end={end} />
        </Section>

        <Section title="Progress by direction"
          sub="The same story split by what is being measured. Each panel is one benchmark: dots are models, the line is the best score so far.">
          <Directions directions={data.directions} ctx={ctx} end={end} />
        </Section>

        <Section title="How long a task can a model finish alone?"
          sub="METR measures the length of software task, in human working time, that a model completes half the time. The scale is logarithmic: each gridline is a much longer task than the one below."
          note="Thin vertical bars are METR's 95% confidence ranges, which are wide for the newest models.">
          <Horizon data={data.horizon} ctx={ctx} end={end} />
        </Section>

        <Section title="What the models work on"
          sub="Notable models released each year, counted by the kind of data they handle. A model that handles several kinds is counted in each."
          note={`The ${end.slice(0, 4)} column is a partial year.`}>
          <Modalities releases={data.releases} ctx={ctx} end={end} />
        </Section>

        <footer className="mt-16 border-t border-slate-800 pt-5 text-[12px] leading-relaxed text-slate-500">
          Data: <a className="text-sky-300 hover:underline" href={data.source.url}>{data.source.name}</a>, {data.source.license}
          {data.source.retrieved ? `, retrieved ${data.source.retrieved.slice(0, 10)}` : ""}. {data.source.citation}{" "}
          Task-length measurements by METR, via Epoch AI. Grouping into directions is ours.{" "}
          <a className="text-sky-300 hover:underline" href="/data/models.json">Download the data behind this page</a>.
        </footer>
      </main>

      {tip && (
        <div className="pointer-events-none fixed z-50 max-w-[300px] rounded-md border border-slate-700 bg-[#0b1520] px-3 py-2 shadow-2xl"
          style={{ left: Math.min(tip.x + 14, (typeof window !== "undefined" ? window.innerWidth : 1200) - 310), top: tip.y + 14 }}>
          <div className="flex items-center gap-2 text-[13px] font-semibold text-slate-50">
            {tip.lab && <i className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: LAB[tip.lab] }} />}
            {tip.title}
          </div>
          <div className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[12px]">
            {tip.rows.map(([k, v], n) => (
              <div key={n} className="contents">
                <span className="text-slate-500">{k}</span><span className="text-slate-200">{v}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
