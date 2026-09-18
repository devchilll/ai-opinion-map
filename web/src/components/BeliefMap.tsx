"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { Html, Line, OrbitControls } from "@react-three/drei";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

type Cell = [number, number, number, string] | null;
type Person = {
  id: string; name: string; role: string; kind: string; headline: boolean;
  axes: Record<string, Cell[]>; axes_allowed: string[];
  enters_at: string | null; contradictions: number; notes?: string;
};
type EventRow = {
  id: string; date: string; title: string; summary: string;
  category: string; importance: number; people: string[]; sources: string[];
};
export type Credit = { license: string; artist: string; file_page: string; license_url: string };

export type Positions = {
  synthetic: boolean; generated_at: string; months: string[];
  axes: Record<string, { label: string; low: string; high: string }>;
  people: Person[]; events?: EventRow[]; credits?: Record<string, Credit>;
};

const SCALE = 1.4;
const AXIS_KEYS = ["X", "Y", "Z"] as const;
// Axis reaches past the maximum possible score so nobody ever sits outside the frame.
const L = 3 * SCALE * 1.25;
const AXIS = "#8fb9cf";

/** Where a date sits along the full timeline, 0..1. */
function monthFraction(date: string, months: string[]): number {
  const idx = months.indexOf(date.slice(0, 7));
  if (idx >= 0) return idx / Math.max(1, months.length - 1);
  return date.slice(0, 7) < months[0] ? 0 : 1;
}


/** null = do not draw. `free` lists axes that are structurally undefined for this
 *  entity, which render as a line through that dimension instead of a false point. */
function coords(p: Person, i: number): { pos: [number, number, number]; free: string[] } | null {
  const out: number[] = [];
  const free: string[] = [];
  for (const a of AXIS_KEYS) {
    if (!p.axes_allowed.includes(a)) { out.push(0); free.push(a); continue; }
    const cell = p.axes[a]?.[i];
    if (!cell) return null;                 // allowed but under-evidenced
    out.push(cell[0] * SCALE);
  }
  return { pos: [out[0], out[1], out[2]], free };
}

/** Which allowed axes have no evidence at month i. Empty = renderable. */
function missingAxes(p: Person, i: number): string[] {
  return AXIS_KEYS.filter((a) => p.axes_allowed.includes(a) && !p.axes[a]?.[i]);
}

/** Nearest month where this person renders, or null. */
function nearestVisibleMonth(p: Person, i: number, total: number): number | null {
  for (let d = 1; d < total; d++) {
    if (i + d < total && missingAxes(p, i + d).length === 0) return i + d;
    if (i - d >= 0 && missingAxes(p, i - d).length === 0) return i - d;
  }
  return null;
}

function trail(p: Person, i: number, months: number): THREE.Vector3[] {
  const pts: THREE.Vector3[] = [];
  for (let k = Math.max(0, i - months); k <= i; k++) {
    const c = coords(p, k);
    if (c) pts.push(new THREE.Vector3(...c.pos));
  }
  return pts;
}

function Node({ p, i, onPick, selected, dim }: {
  p: Person; i: number; onPick: (p: Person) => void; selected: boolean; dim: boolean;
}) {
  const ref = useRef<THREE.Group>(null);
  const c = coords(p, i);
  const target = useRef(new THREE.Vector3());

  useFrame(() => {
    if (!ref.current || !c) return;
    target.current.set(...c.pos);
    ref.current.position.lerp(target.current, 0.16);
  });

  if (!c) return null;
  const isPublic = p.kind === "public";
  const isPolicy = p.kind === "policy";
  const firstAxis = p.axes_allowed[0];
  const cell = p.axes[firstAxis]?.[i];
  const dispersion = cell ? cell[1] : 0;
  const sparse = cell ? cell[3] === "s" : false;
  const r = isPublic ? 0.3 : 0.17;
  const color = isPublic ? "#e3b765" : isPolicy ? "#9fb3c0" : "#7fd4ff";

  return (
    <group ref={ref} position={c.pos}>
      <mesh onClick={(e) => { e.stopPropagation(); onPick(p); }}>
        {isPolicy ? <boxGeometry args={[r * 1.6, r * 1.6, r * 1.6]} />
                  : <sphereGeometry args={[r, 32, 32]} />}
        <meshStandardMaterial
          color={selected ? "#ffffff" : color}
          emissive={selected ? "#5a8ba8" : color} emissiveIntensity={selected ? 1.1 : 0.45}
          transparent opacity={dim ? 0.2 : sparse ? 0.5 : 0.97}
        />
      </mesh>

      {/* Structurally undefined axis: a bar through that dimension, never a point. */}
      {c.free.map((a) => {
        const dir: [number, number, number] =
          a === "X" ? [L, 0, 0] : a === "Y" ? [0, L, 0] : [0, 0, L];
        const seg: [number, number, number][] = [
          [-dir[0], -dir[1], -dir[2]], dir,
        ];
        return <Line key={a} points={seg} color={color} lineWidth={2}
                     transparent opacity={dim ? 0.06 : 0.3} dashed dashSize={0.12} gapSize={0.1} />;
      })}

      {dispersion > 0.8 && !dim && (
        <mesh>
          <sphereGeometry args={[r + dispersion * 0.2, 16, 16]} />
          <meshBasicMaterial color={color} transparent opacity={0.06} />
        </mesh>
      )}

      <Html position={[0, r + 0.12, 0]} center distanceFactor={13}
            style={{ pointerEvents: "none", whiteSpace: "nowrap", userSelect: "none", opacity: dim ? 0.25 : 1 }}>
        <span style={{
          color: selected ? "#fff" : isPublic ? "#e3b765" : "#cfe4f0",
          fontSize: isPublic ? 16 : 13, fontWeight: isPublic || selected ? 700 : 500,
          letterSpacing: 0.2, textShadow: "0 1px 4px #000, 0 0 10px #000",
        }}>{p.name}</span>
      </Html>
    </group>
  );
}

function AxisFrame({ axes }: { axes: Positions["axes"] }) {
  const spec: [[number, number, number], string, string][] = [
    [[L, 0, 0], axes.X.high, axes.X.low],
    [[0, L, 0], axes.Y.high, axes.Y.low],
    [[0, 0, L], axes.Z.high, axes.Z.low],
  ];
  const label = (text: string) => (
    <span style={{
      color: AXIS, fontSize: 21, fontWeight: 800, letterSpacing: 1.8,
      textTransform: "uppercase", whiteSpace: "nowrap", userSelect: "none",
      textShadow: "0 2px 10px #000, 0 0 24px #000",
    }}>{text}</span>
  );
  return (
    <group>
      <gridHelper args={[9, 18, "#1b3040", "#12202c"]} position={[0, -L, 0]} />
      {spec.map(([end, hi, lo], k) => (
        <group key={k}>
          <Line points={[[-end[0], -end[1], -end[2]], end]} color={AXIS}
                lineWidth={5} transparent opacity={0.9} />
          <Html position={[end[0] * 1.1, end[1] * 1.1, end[2] * 1.1]} center distanceFactor={14}
                style={{ pointerEvents: "none", userSelect: "none" }}>{label(hi)}</Html>
          <Html position={[-end[0] * 1.1, -end[1] * 1.1, -end[2] * 1.1]} center distanceFactor={14}
                style={{ pointerEvents: "none", userSelect: "none" }}>{label(lo)}</Html>
        </group>
      ))}
    </group>
  );
}

function Avatar({ p, size = 56 }: { p: Person; size?: number }) {
  const [failed, setFailed] = useState(false);
  const initials = p.name.split(" ").map((w) => w[0]).slice(0, 2).join("");
  const hue = [...p.id].reduce((a, ch) => a + ch.charCodeAt(0), 0) % 360;
  if (failed) {
    return (
      <div style={{ width: size, height: size, borderRadius: 10, flexShrink: 0,
                    background: `linear-gradient(140deg,hsl(${hue} 45% 26%),hsl(${hue} 45% 14%))`,
                    display: "grid", placeItems: "center", color: "#dbeafe",
                    fontSize: size * 0.34, fontWeight: 700 }}>{initials}</div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={`/portraits/${p.id}.jpg`} alt="" width={size} height={size}
         onError={() => setFailed(true)}
         style={{ width: size, height: size, borderRadius: 10, objectFit: "cover", flexShrink: 0 }} />
  );
}

export default function BeliefMap({ data }: { data: Positions }) {
  const credits = data.credits ?? {};
  const [i, setI] = useState(data.months.length - 1);
  const [playing, setPlaying] = useState(false);
  const [picked, setPicked] = useState<Person | null>(null);
  const [trailMonths, setTrailMonths] = useState(12);
  const [showEvents, setShowEvents] = useState(true);
  const [spin, setSpin] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setI((v) => (v >= data.months.length - 1 ? 0 : v + 1)), 95);
    return () => clearInterval(t);
  }, [playing, data.months.length]);

  const headline = useMemo(() => data.people.filter((p) => p.headline), [data.people]);
  const q = query.trim().toLowerCase();
  const matches = useMemo(
    () => (q ? new Set(data.people.filter((p) => p.name.toLowerCase().includes(q))
                          .map((p) => p.id)) : null),
    [data.people, q]
  );
  const month = data.months[i];
  const visible = useMemo(() => headline.filter((p) => coords(p, i)), [headline, i]);
  const hidden = useMemo(
    () => headline.filter((p) => !coords(p, i))
                  .map((p) => ({ p, missing: missingAxes(p, i),
                                 before: p.enters_at ? month < p.enters_at : false })),
    [headline, i, month]
  );
  const searchHits = useMemo(
    () => (q ? data.people.filter((p) => p.name.toLowerCase().includes(q)) : []),
    [data.people, q]
  );


  // The event for the month you are scrubbing through, if any.
  const currentEvents = useMemo(
    () => (data.events ?? []).filter((e) => e.date.slice(0, 7) === month),
    [data.events, month]
  );

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#03070c]">
      {data.synthetic && (
        <div className="absolute inset-x-0 top-0 z-30 bg-amber-500 px-4 py-1.5 text-center
                        text-xs font-semibold tracking-wide text-black">
          SYNTHETIC FIXTURE — coordinates are generated, not derived from real statements.
          Positions and clusters here mean nothing yet.
        </div>
      )}

      <header className="pointer-events-none absolute left-7 top-12 z-30 max-w-sm">
        <h1 className="text-[26px] font-semibold leading-tight text-slate-50">
          How the people shaping AI see its future
        </h1>
        <p className="mt-1.5 text-[13px] text-slate-400">
          {visible.length} of {headline.length} on the map · {month}
        </p>
        {hidden.length > 0 && (
          <p className="pointer-events-auto mt-1 text-[11px] text-slate-500">
            {hidden.length} hidden:{" "}
            {hidden.filter((h) => h.before).length} not yet in the record,{" "}
            {hidden.filter((h) => !h.before).length} without enough evidence this month
          </p>
        )}
      </header>

      <div className="absolute left-7 top-[11rem] z-30 w-72">
        <input value={query} onChange={(e) => setQuery(e.target.value)}
               placeholder="Search a person…"
               className="w-full rounded-md border border-slate-700/80 bg-slate-900/70 px-3 py-1.5
                          text-sm text-slate-100 placeholder:text-slate-500
                          focus:border-slate-500 focus:outline-none" />
        {q && (
          <div className="mt-1.5 space-y-1 rounded-md border border-slate-800
                          bg-slate-900/80 p-2 text-[11px]">
            {searchHits.length === 0 && <p className="text-slate-500">no one by that name</p>}
            {searchHits.slice(0, 6).map((hit) => {
              const miss = missingAxes(hit, i);
              const jump = miss.length ? nearestVisibleMonth(hit, i, data.months.length) : null;
              return (
                <div key={hit.id}>
                  <button onClick={() => { setPicked(hit); if (jump !== null) setI(jump); }}
                          className="text-left text-slate-200 hover:underline">
                    {hit.name}
                  </button>
                  {miss.length === 0 ? (
                    <span className="ml-1.5 text-slate-500">on the map</span>
                  ) : (
                    <span className="ml-1.5 text-amber-600/90">
                      hidden — no evidence for{" "}
                      {miss.map((a) => data.axes[a].label.toLowerCase()).join(", ")} in {month}
                      {jump !== null && ` · jump to ${data.months[jump]}`}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="absolute right-7 top-12 z-30 flex flex-col items-end gap-2 text-xs">
        <label className="flex items-center gap-2 text-slate-400">
          <span>trails</span>
          <select value={trailMonths} onChange={(e) => setTrailMonths(Number(e.target.value))}
                  className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-slate-200">
            <option value={0}>off</option>
            <option value={6}>6 months</option>
            <option value={12}>12 months</option>
            <option value={36}>36 months</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-slate-400">
          <span>events</span>
          <input type="checkbox" checked={showEvents}
                 onChange={(e) => setShowEvents(e.target.checked)} className="accent-sky-400" />
        </label>
        <label className="flex items-center gap-2 text-slate-400">
          <span>auto-rotate</span>
          <input type="checkbox" checked={spin}
                 onChange={(e) => setSpin(e.target.checked)} className="accent-sky-400" />
        </label>
      </div>

      <Canvas
        camera={{ position: [16, 7.5, 9.5], fov: 40 }}
        gl={{ preserveDrawingBuffer: true, antialias: true }}
        onPointerMissed={() => setPicked(null)}
      >
        <ambientLight intensity={0.6} />
        <pointLight position={[9, 9, 9]} intensity={130} />
        <AxisFrame axes={data.axes} />
        <Suspense fallback={null}>
          {visible.map((p) => (
            <group key={p.id}>
              {trailMonths > 0 && (() => {
                const pts = trail(p, i, trailMonths);
                return pts.length > 1
                  ? <Line points={pts} color="#3f7f9c" lineWidth={1}
                          transparent
                          opacity={picked?.id === p.id ? 0.55 : picked ? 0.05 : 0.16} />
                  : null;
              })()}
              <Node p={p} i={i} onPick={setPicked}
                    selected={picked?.id === p.id || (!!matches && matches.has(p.id))}
                    dim={(!!picked && picked.id !== p.id) ||
                         (!!matches && !matches.has(p.id))} />
            </group>
          ))}

        </Suspense>
        <OrbitControls enablePan={false} autoRotate={spin && !picked}
                       autoRotateSpeed={0.22} minDistance={8} maxDistance={30} />
      </Canvas>

      <div className="absolute inset-x-0 bottom-0 z-30 bg-gradient-to-t from-[#03070c]
                      via-[#03070c]/85 to-transparent px-7 pb-5 pt-16">
        <div className="flex items-center gap-4">
          <button onClick={() => setPlaying((v) => !v)}
                  className="w-20 rounded bg-slate-100 px-4 py-1.5 text-sm font-medium text-slate-900">
            {playing ? "Pause" : "Play"}
          </button>
          <span className="w-20 font-mono text-sm text-slate-200">{month}</span>
          <div className="relative flex-1">
            {showEvents && (data.events ?? []).map((e) => (
              <button key={e.id} onClick={() => setI(
                        Math.round(monthFraction(e.date, data.months) * (data.months.length - 1)))}
                      title={`${e.date} · ${e.title}`}
                      className="absolute -top-3 h-3 w-[2px] -translate-x-1/2 rounded
                                 bg-slate-500 hover:bg-slate-200"
                      style={{ left: `${monthFraction(e.date, data.months) * 100}%`,
                               opacity: e.importance >= 5 ? 0.95 : 0.45 }} />
            ))}
            <input type="range" min={0} max={data.months.length - 1} value={i}
                   onChange={(e) => setI(Number(e.target.value))}
                   className="h-1.5 w-full accent-sky-400" />
          </div>
          <span className="font-mono text-xs text-slate-500">
            {data.months[0]} – {data.months[data.months.length - 1]}
          </span>
        </div>
      </div>

      {picked && (
        <aside className="absolute right-7 top-28 z-40 w-[22rem] rounded-xl border
                          border-slate-700 bg-[#070d15] p-5 text-slate-200 shadow-2xl">
          <div className="flex gap-3">
            <Avatar p={picked} />
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold leading-tight">{picked.name}</h2>
              <p className="mt-0.5 text-xs leading-snug text-slate-400">{picked.role}</p>
            </div>
            <button onClick={() => setPicked(null)} className="text-lg text-slate-500">×</button>
          </div>

          <dl className="mt-4 space-y-2 text-sm">
            {(["X", "Y", "Z", "W"] as const).map((a) => {
              const allowed = picked.axes_allowed.includes(a);
              const cell = picked.axes[a]?.[i];
              return (
                <div key={a} className="border-b border-slate-800/80 pb-1.5">
                  <div className="flex justify-between">
                    <dt className="text-slate-400">{data.axes[a].label}</dt>
                    <dd className="font-mono text-slate-100">
                      {!allowed ? <span className="text-slate-600">not applicable</span>
                        : cell ? cell[0].toFixed(2)
                        : <span className="text-amber-600/80">no evidence</span>}
                    </dd>
                  </div>
                  {allowed && cell && (
                    <div className="mt-1 h-1 rounded bg-slate-800">
                      <div className="h-1 rounded bg-sky-400"
                           style={{ width: `${((cell[0] + 3) / 6) * 100}%` }} />
                    </div>
                  )}
                </div>
              );
            })}
          </dl>

          <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
            enters the map {picked.enters_at ?? "—"}
            {picked.kind === "policy" &&
              " · policy figure: scored on stated policy positions only, never on capability beliefs"}
            {picked.kind === "public" &&
              " · survey data, not statements. No position on open weights, because nobody polls it"}
          </p>
          {picked.notes && (
            <p className="mt-2 text-[11px] leading-relaxed text-slate-500">{picked.notes}</p>
          )}
          {credits[picked.id] && (
            <p className="mt-2 text-[10px] leading-relaxed text-slate-600">
              Portrait:{" "}
              <a href={credits[picked.id].file_page} target="_blank" rel="noreferrer"
                 className="underline hover:text-slate-400">
                {credits[picked.id].artist || "Wikimedia Commons"}
              </a>{" "}
              ·{" "}
              <a href={credits[picked.id].license_url} target="_blank" rel="noreferrer"
                 className="underline hover:text-slate-400">
                {credits[picked.id].license}
              </a>
            </p>
          )}
        </aside>
      )}

      {showEvents && currentEvents.length > 0 && (
        <aside className="absolute bottom-28 left-7 z-40 w-[23rem] rounded-xl border
                          border-slate-700 bg-[#070d15] p-4 text-slate-200 shadow-2xl">
          {currentEvents.slice(0, 2).map((ev) => (
            <div key={ev.id} className="border-slate-800 [&+div]:mt-3 [&+div]:border-t
                                        [&+div]:pt-3">
              <p className="font-mono text-[11px] text-slate-500">{ev.date}</p>
              <h3 className="mt-0.5 font-semibold leading-tight">{ev.title}</h3>
              <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{ev.summary}</p>
              <div className="mt-2 flex flex-wrap gap-3">
                {ev.sources.slice(0, 2).map((src, k) => (
                  <a key={k} href={src} target="_blank" rel="noreferrer"
                     className="text-[11px] text-slate-400 underline hover:text-slate-200">
                    source {k + 1}
                  </a>
                ))}
              </div>
            </div>
          ))}
          <p className="mt-3 text-[10px] leading-relaxed text-slate-600">
            Context for this month. An event near a movement is not its cause.
          </p>
        </aside>
      )}
    </div>
  );
}
