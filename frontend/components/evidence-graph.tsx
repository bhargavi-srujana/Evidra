"use client";

import { useCallback, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type {
  Claim,
  ClaimCluster,
  PairwiseContradiction,
  Study,
} from "@/lib/types";
import {
  effectBadge,
  effectForStudy,
  effectNodeColor,
  formatEffectLabel,
} from "@/lib/effects";
import { cn } from "@/lib/utils";

interface EvidenceGraphProps {
  query: string;
  clusters?: ClaimCluster[];
  studies?: Study[];
  claims?: Claim[];
  contradictions?: PairwiseContradiction[];
  className?: string;
  /**
   * "paper" renders light nodes with thin dark edges for embedding on white
   * paper sheets (reference board style); "dark" is the glass-dashboard look.
   */
  tone?: "dark" | "paper";
  /** Shorter canvas for collage embedding. */
  compact?: boolean;
}

type SelectedNode =
  | { kind: "question" }
  | { kind: "cluster"; clusterId: string }
  | { kind: "study"; studyId: string };

const DIM_OPACITY = 0.35;
const EDGE_STYLE = {
  dark: { stroke: "#52525b", strokeWidth: 1.5 },
  paper: { stroke: "#71717a", strokeWidth: 1.25 },
} as const;

/**
 * Node surface per tone: charcoal cards with light labels on the dark
 * dashboard, white cards with dark labels on paper sheets.
 */
const NODE_SURFACE = {
  dark: { backgroundColor: "#18181b", color: "#e4e4e7", fontSize: 12 },
  paper: {
    backgroundColor: "#ffffff",
    color: "#27272a",
    fontSize: 11,
    boxShadow: "0 1px 3px rgba(0,0,0,0.25)",
  },
} as const;

const ACCENT = {
  dark: { question: "#60a5fa", cluster: "#a78bfa" },
  paper: { question: "#2563eb", cluster: "#7c3aed" },
} as const;

function truncate(text: string, max = 48): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

// Defined in the lightweight skeletons module so routes can show the
// placeholder without statically pulling @xyflow/react into their bundle.
// NOTE: import it from "@/components/skeletons" to keep the code-split;
// this alias only preserves backwards compatibility.
export { EvidenceGraphSkeleton } from "./skeletons";

export default function EvidenceGraph({
  query,
  clusters = [],
  studies = [],
  claims = [],
  contradictions = [],
  className,
  tone = "dark",
  compact = false,
}: EvidenceGraphProps) {
  const [selected, setSelected] = useState<SelectedNode | null>(null);
  const surface = NODE_SURFACE[tone];
  const accent = ACCENT[tone];
  const edgeStyle = EDGE_STYLE[tone];

  const claimById = useMemo(
    () => new Map(claims.map((c) => [c.claim_id, c])),
    [claims],
  );
  const studyById = useMemo(
    () => new Map(studies.map((s) => [s.study_id, s])),
    [studies],
  );

  /** Study IDs reachable from a cluster via shared claims. */
  const clusterStudies = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const cluster of clusters) {
      const members = new Set<string>();
      for (const claimId of cluster.claim_ids) {
        const claim = claimById.get(claimId);
        if (claim) members.add(claim.study_id);
      }
      map.set(cluster.cluster_id, members);
    }
    return map;
  }, [clusters, claimById]);

  const { nodes, edges, neighborMap } = useMemo(() => {
    const builtNodes: Node[] = [];
    const builtEdges: Edge[] = [];
    const neighbors = new Map<string, Set<string>>();
    const link = (a: string, b: string) => {
      if (!neighbors.get(a)) neighbors.set(a, new Set());
      if (!neighbors.get(b)) neighbors.set(b, new Set());
      neighbors.get(a)?.add(b);
      neighbors.get(b)?.add(a);
    };

    const questionId = "question";
    builtNodes.push({
      id: questionId,
      type: "input",
      position: { x: 340, y: 0 },
      data: { label: truncate(query || "Research question", 60) },
      style: {
        ...surface,
        borderColor: accent.question,
        borderWidth: 2,
        width: 180,
      },
    });

    const nClusters = Math.max(clusters.length, 1);
    // Roomy layout: up to 3 clusters share one row; more spill onto a
    // second staggered tier so labels never stack into a dark mass.
    const twoTier = nClusters > 3;
    clusters.forEach((cluster, i) => {
      const id = `cluster:${cluster.cluster_id}`;
      let x: number;
      let y: number;
      if (nClusters === 1) {
        x = 340;
        y = 170;
      } else if (!twoTier) {
        x = 40 + (i * 760) / (nClusters - 1) - 60;
        y = 170;
      } else {
        const tier = i % 2;
        const k = Math.floor(i / 2);
        const perTier = Math.ceil(nClusters / 2);
        x = perTier === 1 ? 340 : 40 + (k * 760) / (perTier - 1) - 60;
        y = tier === 0 ? 150 : 270;
      }
      builtNodes.push({
        id,
        position: { x, y },
        data: { label: truncate(cluster.topic, 32) },
        style: {
          ...surface,
          borderColor: accent.cluster,
          borderWidth: 1.5,
          width: 150,
        },
      });
      builtEdges.push({
        id: `e-q-${cluster.cluster_id}`,
        source: questionId,
        target: id,
        style: { ...edgeStyle },
      });
      link(questionId, id);
    });

    const studiesTop = (twoTier ? 270 : 170) + 160;
    const perRow = 3;
    studies.forEach((study, i) => {
      const id = `study:${study.study_id}`;
      const direction = effectForStudy(study.study_id, claims);
      const color = direction ? effectNodeColor(direction) : "#71717a";
      const row = Math.floor(i / perRow);
      const col = i % perRow;
      builtNodes.push({
        id,
        position: { x: 60 + col * 230, y: studiesTop + row * 140 },
        data: { label: `paper snippet: ${truncate(study.title, 28)}` },
        style: {
          ...surface,
          borderColor: color,
          borderWidth: 1.5,
          width: 170,
        },
      });
      for (const cluster of clusters) {
        if (clusterStudies.get(cluster.cluster_id)?.has(study.study_id)) {
          const target = `cluster:${cluster.cluster_id}`;
          builtEdges.push({
            id: `e-${cluster.cluster_id}-${study.study_id}`,
            source: target,
            target: id,
            style: { ...edgeStyle },
          });
          link(target, id);
        }
      }
    });

    for (const c of contradictions) {
      const a = `study:${c.study_a_id}`;
      const b = `study:${c.study_b_id}`;
      if (studyById.has(c.study_a_id) && studyById.has(c.study_b_id)) {
        builtEdges.push({
          id: `e-contra-${c.study_a_id}-${c.study_b_id}`,
          source: a,
          target: b,
          label: "contradicts",
          animated: true,
          style: { stroke: "#ef4444", strokeWidth: 2, strokeDasharray: "6 3" },
          labelStyle: { fill: "#7f1d1d", fontSize: 10, fontWeight: 700 },
          labelBgStyle: { fill: "#fecdd3" },
        });
        link(a, b);
      }
    }

    return { nodes: builtNodes, edges: builtEdges, neighborMap: neighbors };
  }, [query, clusters, studies, claims, contradictions, studyById, clusterStudies, surface, accent, edgeStyle]);

  const selectedKey = useMemo(() => {
    if (!selected) return null;
    if (selected.kind === "question") return "question";
    if (selected.kind === "cluster") return `cluster:${selected.clusterId}`;
    return `study:${selected.studyId}`;
  }, [selected]);

  const visibleNodes = useMemo(() => {
    if (!selectedKey) return nodes;
    const keep = new Set([selectedKey, ...(neighborMap.get(selectedKey) ?? [])]);
    return nodes.map((node) => ({
      ...node,
      style: {
        ...node.style,
        opacity: keep.has(node.id) ? 1 : DIM_OPACITY,
      },
    }));
  }, [nodes, selectedKey, neighborMap]);

  const visibleEdges = useMemo(() => {
    if (!selectedKey) return edges;
    return edges.map((edge) => {
      const active = edge.source === selectedKey || edge.target === selectedKey;
      return {
        ...edge,
        style: { ...edge.style, opacity: active ? 1 : DIM_OPACITY },
      };
    });
  }, [edges, selectedKey]);

  const detail = useMemo(() => {
    if (!selected) return null;
    if (selected.kind === "question") {
      return {
        title: "Research question",
        subtitle: query,
        lines: [
          `${studies.length} studies`,
          `${clusters.length} topic clusters`,
          `${contradictions.length} contradictions`,
        ],
      };
    }
    if (selected.kind === "cluster") {
      const cluster = clusters.find((c) => c.cluster_id === selected.clusterId);
      if (!cluster) return null;
      const memberClaims = cluster.claim_ids
        .map((id) => claimById.get(id))
        .filter((c): c is Claim => Boolean(c));
      return {
        title: cluster.topic,
        subtitle: `${memberClaims.length} claims`,
        lines: memberClaims.slice(0, 5).map((c) => `• ${c.text}`),
      };
    }
    const study = studyById.get(selected.studyId);
    if (!study) return null;
    const studyClaims = claims.filter((c) => c.study_id === study.study_id);
    const related = contradictions.filter(
      (c) => c.study_a_id === study.study_id || c.study_b_id === study.study_id,
    ).length;
    return {
      title: study.title,
      subtitle: `${study.authors.map((a) => a.name).join(", ") || "Unknown authors"} · ${study.year ?? "Year unknown"}${related > 0 ? ` · ${related} contradiction${related > 1 ? "s" : ""}` : ""}`,
      lines: studyClaims.slice(0, 5).map((c) => `• ${c.text}`),
    };
  }, [selected, query, studies, clusters, contradictions, claimById, studyById, claims]);

  const legend: Array<{ label: string; color: string }> = [
    { label: "Question", color: accent.question },
    { label: "Topic cluster", color: accent.cluster },
    { label: "Positive", color: effectNodeColor("increases") },
    { label: "Negative", color: effectNodeColor("decreases") },
    { label: "Conditional", color: effectNodeColor("conditional") },
  ];
  const onPaper = tone === "paper";

  // Stable callbacks so <ReactFlow> doesn't re-subscribe on every render.
  const handleNodeClick = useCallback(
    (_: unknown, node: { id: string }) => {
      if (node.id === "question") setSelected({ kind: "question" });
      else if (node.id.startsWith("cluster:"))
        setSelected({
          kind: "cluster",
          clusterId: node.id.slice("cluster:".length),
        });
      else if (node.id.startsWith("study:"))
        setSelected({ kind: "study", studyId: node.id.slice("study:".length) });
    },
    [],
  );
  const handlePaneClick = useCallback(() => setSelected(null), []);

  // Effect badge for the selected study: computed once, not 3x per render.
  const selectedEffect = useMemo(
    () =>
      selected?.kind === "study"
        ? effectForStudy(selected.studyId, claims)
        : null,
    [selected, claims],
  );

  if (studies.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        The evidence graph will appear here once studies are retrieved.
      </p>
    );
  }

  return (
    <div className={cn("space-y-2", className)}>
      <div
        className={cn(
          "w-full overflow-hidden",
          compact ? "h-[360px]" : "h-[380px]",
          onPaper
            ? "rounded-lg bg-white"
            : "rounded-2xl border border-neutral-800 bg-neutral-950",
        )}
      >
        <ReactFlow
          nodes={visibleNodes}
          edges={visibleEdges}
          onNodeClick={handleNodeClick}
          onPaneClick={handlePaneClick}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          onlyRenderVisibleElements
          colorMode={onPaper ? "light" : "dark"}
          proOptions={{ hideAttribution: true }}
        >
          <Background color={onPaper ? "#d4d4d8" : "#3f3f46"} />
          <Controls />
          {onPaper ? (
            <MiniMap
              pannable
              zoomable
              style={{ backgroundColor: "#f4f4f5" }}
              maskColor="rgba(0, 0, 0, 0.08)"
              className="!m-3 !h-24 !w-36 !overflow-hidden !rounded-xl !border !border-neutral-200"
            />
          ) : (
            <MiniMap
              pannable
              zoomable
              style={{ backgroundColor: "#09090b" }}
              maskColor="rgba(0, 0, 0, 0.55)"
              className="!m-3 !h-28 !w-44 !overflow-hidden !rounded-xl !border !border-neutral-800 !bg-neutral-950"
            />
          )}
        </ReactFlow>
      </div>

      <div
        className={cn(
          "flex flex-wrap items-center gap-3 text-xs",
          onPaper ? "text-neutral-600" : "text-neutral-400",
        )}
      >
        {legend.map(({ label, color }) => (
          <span key={label} className="inline-flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full border-2"
              style={{ borderColor: color }}
              aria-hidden="true"
            />
            {label}
          </span>
        ))}
        {selectedKey ? (
          <button
            type="button"
            onClick={() => setSelected(null)}
            className={cn(
              "ml-auto font-medium underline-offset-4 hover:underline",
              onPaper
                ? "text-neutral-700"
                : "text-neutral-200",
            )}
          >
            Clear selection
          </button>
        ) : (
          <span className="ml-auto">Click a node to inspect claims &amp; papers</span>
        )}
      </div>
      <p className={cn("text-[11px]", onPaper ? "text-neutral-500" : "text-neutral-500")}>
        Force-directed layout of claim snippets and paper snippets — red dashed
        edges mark contradictions.
      </p>

      {detail ? (
        <div
          className={cn(
            "rounded-xl p-4",
            onPaper
              ? "border border-neutral-200 bg-neutral-50"
              : "border border-neutral-700/70 bg-neutral-900/70 backdrop-blur-lg",
          )}
        >
          <h4
            className={cn(
              "text-sm font-semibold",
              onPaper ? "text-neutral-900" : "text-neutral-50",
            )}
          >
            {detail.title}
          </h4>
          <p className={cn("mt-0.5 text-xs", onPaper ? "text-neutral-500" : "text-neutral-400")}>
            {detail.subtitle}
          </p>
          {detail.lines.length > 0 ? (
            <ul className={cn("mt-2 space-y-1 text-xs", onPaper ? "text-neutral-600" : "text-neutral-300")}>
              {detail.lines.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          ) : null}
          {selected?.kind === "study" && selectedEffect ? (
            <span
              className={cn(
                "mt-2 inline-flex rounded-full px-2 py-0.5 text-xs font-medium",
                effectBadge(selectedEffect),
              )}
            >
              {formatEffectLabel(selectedEffect)}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
