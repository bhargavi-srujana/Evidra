"use client";

import { useMemo, useState } from "react";
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
  EFFECT_BADGE,
  EFFECT_NODE_COLOR,
  effectForStudy,
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
}

type SelectedNode =
  | { kind: "question" }
  | { kind: "cluster"; clusterId: string }
  | { kind: "study"; studyId: string };

const QUESTION_COLOR = "#2563eb";
const CLUSTER_COLOR = "#8b5cf6";
const DIM_OPACITY = 0.4;

/**
 * Explicit node surface. XYFlow's default node text color is `inherit`, so
 * labels pick up the page text color and vanish against the default node
 * background whenever the app theme flips (light text on white nodes in
 * dark mode). Pinning bg + text + size keeps labels legible in both themes.
 */
const NODE_TEXT_STYLE = {
  backgroundColor: "#ffffff",
  color: "#18181b",
  fontSize: 12,
} as const;

function truncate(text: string, max = 48): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export function EvidenceGraphSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading evidence graph"
      className="h-[380px] w-full animate-pulse rounded-2xl bg-zinc-100 dark:bg-zinc-900"
    />
  );
}

export default function EvidenceGraph({
  query,
  clusters = [],
  studies = [],
  claims = [],
  contradictions = [],
  className,
}: EvidenceGraphProps) {
  const [selected, setSelected] = useState<SelectedNode | null>(null);

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
        ...NODE_TEXT_STYLE,
        borderColor: QUESTION_COLOR,
        borderWidth: 2,
        width: 180,
      },
    });

    const nClusters = Math.max(clusters.length, 1);
    clusters.forEach((cluster, i) => {
      const id = `cluster:${cluster.cluster_id}`;
      const x = nClusters === 1 ? 340 : 40 + i * (720 / Math.max(nClusters - 1, 1)) - 70;
      builtNodes.push({
        id,
        position: { x, y: 160 },
        data: { label: truncate(cluster.topic, 40) },
        style: {
          ...NODE_TEXT_STYLE,
          borderColor: CLUSTER_COLOR,
          borderWidth: 2,
          width: 150,
        },
      });
      builtEdges.push({ id: `e-q-${cluster.cluster_id}`, source: questionId, target: id });
      link(questionId, id);
    });

    const perRow = 4;
    studies.forEach((study, i) => {
      const id = `study:${study.study_id}`;
      const direction = effectForStudy(study.study_id, claims);
      const color = direction ? EFFECT_NODE_COLOR[direction] : "#71717a";
      const row = Math.floor(i / perRow);
      const col = i % perRow;
      builtNodes.push({
        id,
        position: { x: 40 + col * 200, y: 320 + row * 110 },
        data: { label: truncate(study.title, 36) },
        style: {
          ...NODE_TEXT_STYLE,
          borderColor: color,
          borderWidth: 2,
          width: 170,
        },
      });
      for (const cluster of clusters) {
        if (clusterStudies.get(cluster.cluster_id)?.has(study.study_id)) {
          const target = `cluster:${cluster.cluster_id}`;
          builtEdges.push({ id: `e-${cluster.cluster_id}-${study.study_id}`, source: target, target: id });
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
          style: { stroke: "#f43f5e", strokeDasharray: "6 3" },
          labelStyle: { fill: "#18181b", fontSize: 10 },
          labelBgStyle: { fill: "#ffffff" },
        });
        link(a, b);
      }
    }

    return { nodes: builtNodes, edges: builtEdges, neighborMap: neighbors };
  }, [query, clusters, studies, claims, contradictions, studyById, clusterStudies]);

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
      subtitle: `${study.authors.map((a) => a.name).join(", ") || "Unknown authors"} · ${study.year}${related > 0 ? ` · ${related} contradiction${related > 1 ? "s" : ""}` : ""}`,
      lines: studyClaims.slice(0, 5).map((c) => `• ${c.text}`),
    };
  }, [selected, query, studies, clusters, contradictions, claimById, studyById, claims]);

  const legend: Array<{ label: string; color: string }> = [
    { label: "Question", color: QUESTION_COLOR },
    { label: "Topic cluster", color: CLUSTER_COLOR },
    { label: "Positive", color: EFFECT_NODE_COLOR.increases },
    { label: "Negative", color: EFFECT_NODE_COLOR.decreases },
    { label: "Conditional", color: EFFECT_NODE_COLOR.conditional },
  ];

  if (studies.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        The evidence graph will appear here once studies are retrieved.
      </p>
    );
  }

  return (
    <div className={cn("space-y-2", className)}>
      <div className="h-[380px] w-full overflow-hidden rounded-2xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
        <ReactFlow
          nodes={visibleNodes}
          edges={visibleEdges}
          onNodeClick={(_, node) => {
            if (node.id === "question") setSelected({ kind: "question" });
            else if (node.id.startsWith("cluster:"))
              setSelected({ kind: "cluster", clusterId: node.id.slice("cluster:".length) });
            else if (node.id.startsWith("study:"))
              setSelected({ kind: "study", studyId: node.id.slice("study:".length) });
          }}
          onPaneClick={() => setSelected(null)}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-500 dark:text-zinc-400">
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
            className="ml-auto font-medium text-zinc-700 underline-offset-4 hover:underline dark:text-zinc-200"
          >
            Clear selection
          </button>
        ) : (
          <span className="ml-auto">Click a node to inspect claims &amp; papers</span>
        )}
      </div>

      {detail ? (
        <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <h4 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
            {detail.title}
          </h4>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
            {detail.subtitle}
          </p>
          {detail.lines.length > 0 ? (
            <ul className="mt-2 space-y-1 text-xs text-zinc-600 dark:text-zinc-300">
              {detail.lines.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          ) : null}
          {selected?.kind === "study" &&
          effectForStudy(selected.studyId, claims) ? (
            <span
              className={cn(
                "mt-2 inline-flex rounded-full px-2 py-0.5 text-xs font-medium",
                EFFECT_BADGE[effectForStudy(selected.studyId, claims) ?? "unclear"],
              )}
            >
              {formatEffectLabel(effectForStudy(selected.studyId, claims) ?? "unclear")}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
