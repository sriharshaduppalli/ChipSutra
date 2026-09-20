const ROWS = {
  uvm: [["test"], ["env", "ral"], ["agent"], ["sequencer", "driver", "monitor", "scoreboard"], ["if"], ["dut", "vip"]],
  sv: [["test"], ["env"], ["generator", "monitor", "scoreboard"], ["driver"], ["if"], ["dut", "vip"]],
  ovm: [["test"], ["env"], ["agent"], ["driver", "monitor", "scoreboard"], ["if"], ["dut"]],
  vmm: [["test"], ["env"], ["driver", "monitor", "scoreboard"], ["if"], ["dut"]],
  procedural: [["top"], ["dut"]],
};

const BOX = { w: 132, h: 36, gapX: 16, gapY: 28, padX: 24, padY: 20 };

function layout(nodes, methodology) {
  const byId = Object.fromEntries((nodes || []).map((n) => [n.id, n]));
  const rows = (ROWS[methodology] || ROWS.sv)
    .map((ids) => ids.map((id) => byId[id]).filter(Boolean))
    .filter((r) => r.length);
  const maxCols = Math.max(1, ...rows.map((r) => r.length));
  const width = BOX.padX * 2 + maxCols * BOX.w + (maxCols - 1) * BOX.gapX;
  const height = BOX.padY * 2 + rows.length * BOX.h + (rows.length - 1) * BOX.gapY;
  const pos = {};
  rows.forEach((row, ri) => {
    const rowW = row.length * BOX.w + (row.length - 1) * BOX.gapX;
    const x0 = (width - rowW) / 2;
    row.forEach((n, ci) => {
      pos[n.id] = { x: x0 + ci * (BOX.w + BOX.gapX), y: BOX.padY + ri * (BOX.h + BOX.gapY), ...n };
    });
  });
  return { pos, width, height };
}

function boxFill(n) {
  if (!n.present) return "#1A212D";
  if (n.role === "dut") return "#064E3B";
  if (n.role === "vip") return "#422006";
  if (n.role === "scoreboard") return "#0B3A4A";
  return "#0F172A";
}

function boxStroke(n) {
  if (!n.present) return "#EF4444";
  if (n.role === "vip") return "#F59E0B";
  if (n.role === "dut") return "#10B981";
  return "#334155";
}

export default function TbArchitecture({ architecture, review }) {
  if (!architecture) {
    return (
      <div className="p-8 font-mono text-xs text-slate-500" data-testid="tb-arch-empty">
        Generate a testbench to review its architecture.
      </div>
    );
  }
  const { pos, width, height } = layout(architecture.nodes, architecture.methodology);
  const verdictColor =
    architecture.verdict === "ok"
      ? "text-emerald-400"
      : architecture.verdict === "gaps"
        ? "text-amber-400"
        : "text-red-400";

  const copyMermaid = async () => {
    try {
      await navigator.clipboard.writeText(architecture.mermaid || "");
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="h-full overflow-auto p-4 space-y-3" data-testid="tb-arch-panel">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
            {architecture.title}
            <span className="text-slate-600"> · parsed from generated SV</span>
          </div>
          <div className={`font-mono text-xs mt-1 ${verdictColor}`}>{architecture.summary}</div>
          {review && (
            <div
              className={`font-mono text-[10px] mt-1 ${
                review.verdict === "ok"
                  ? "text-emerald-400"
                  : review.verdict === "review"
                    ? "text-amber-400"
                    : "text-red-400"
              }`}
              data-testid="tb-review-score"
            >
              Quality {review.score}/100 · {review.verdict}
              {review.missing_ports?.length
                ? ` · missing ports: ${review.missing_ports.slice(0, 6).join(", ")}`
                : ""}
              {review.fake_golden ? " · fake golden" : ""}
            </div>
          )}
        </div>
        {architecture.mermaid && (
          <button
            type="button"
            onClick={copyMermaid}
            className="font-mono text-[10px] text-emerald-400 hover:underline shrink-0"
            data-testid="tb-arch-copy-mermaid"
          >
            Copy Mermaid
          </button>
        )}
      </div>

      <svg
        width="100%"
        viewBox={`0 0 ${width} ${height}`}
        className="bg-[#0B0E14] border border-[#1E293B]"
        data-testid="tb-arch-svg"
      >
        {(architecture.edges || []).map((e, i) => {
          const a = pos[e.from];
          const b = pos[e.to];
          if (!a || !b) return null;
          const x1 = a.x + BOX.w / 2;
          const y1 = a.y + BOX.h;
          const x2 = b.x + BOX.w / 2;
          const y2 = b.y;
          const midY = (y1 + y2) / 2;
          return (
            <g key={`${e.from}-${e.to}-${i}`}>
              <path
                d={`M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`}
                fill="none"
                stroke={e.present ? "#10B981" : "#64748B"}
                strokeWidth="1.2"
                strokeDasharray={e.present ? "0" : "4 3"}
              />
              {e.label && (
                <text x={(x1 + x2) / 2} y={midY - 2} textAnchor="middle" fill="#64748B" fontSize="8" fontFamily="JetBrains Mono">
                  {e.label}
                </text>
              )}
            </g>
          );
        })}
        {Object.values(pos).map((n) => (
          <g key={n.id}>
            <rect
              x={n.x}
              y={n.y}
              width={BOX.w}
              height={BOX.h}
              fill={boxFill(n)}
              stroke={boxStroke(n)}
              strokeWidth="1.2"
              strokeDasharray={n.present ? "0" : "4 3"}
              rx="2"
            />
            <text
              x={n.x + BOX.w / 2}
              y={n.y + 15}
              textAnchor="middle"
              fill={n.present ? "#E2E8F0" : "#F87171"}
              fontSize="9"
              fontFamily="JetBrains Mono"
            >
              {(n.label || n.role).length > 18 ? `${(n.label || n.role).slice(0, 17)}…` : n.label || n.role}
            </text>
            <text
              x={n.x + BOX.w / 2}
              y={n.y + 27}
              textAnchor="middle"
              fill="#64748B"
              fontSize="7"
              fontFamily="JetBrains Mono"
            >
              {n.role}
            </text>
          </g>
        ))}
      </svg>

      <div className="space-y-1" data-testid="tb-arch-findings">
        {[
          ...(architecture.findings || []),
          ...((review?.findings || []).filter(
            (f) => !(architecture.findings || []).some((a) => a.title === f.title),
          )),
        ].map((f, i) => (
          <div key={i} className="font-mono text-[11px] text-slate-300">
            <span
              className={
                f.severity === "error"
                  ? "text-red-400"
                  : f.severity === "warn"
                    ? "text-amber-400"
                    : "text-emerald-400"
              }
            >
              [{f.severity}]
            </span>{" "}
            {f.title}
            {f.hint ? <span className="text-slate-500"> — {f.hint}</span> : null}
          </div>
        ))}
      </div>
    </div>
  );
}
