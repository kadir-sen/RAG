"""
Light Graph - Document-level graph for timeline and relationship queries.
Stores nodes (documents) and edges (relationships) as JSON.
No external graph database required.
"""
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field, asdict
from collections import defaultdict

from .logger import logger
from .config import BASE_DIR
from .notice_extractor import NoticeMetadata, NOTICES_DIR

# Graph storage
GRAPH_DIR = BASE_DIR / "data" / "graph"
GRAPH_DIR.mkdir(parents=True, exist_ok=True)
GRAPH_FILE = GRAPH_DIR / "document_graph.json"


@dataclass
class GraphNode:
    """Node representing a document in the graph."""
    doc_id: str
    date: Optional[str]  # ISO format
    sender: Optional[str]
    recipient: Optional[str]
    subject: Optional[str]
    topics: List[str]
    ref_numbers: List[str]
    file_name: str
    doc_type: Optional[str] = None


@dataclass
class GraphEdge:
    """Edge representing a relationship between documents."""
    from_doc: str
    to_doc: str
    edge_type: str  # references, reply_to, same_party, chronological_next, same_topic
    weight: float  # 0.0 to 1.0
    why: str  # Explanation of why this edge exists


@dataclass
class DocumentGraph:
    """Document-level graph structure."""
    nodes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class LightGraph:
    """
    Document-level graph for relationship and timeline queries.
    Uses notice metadata to build edges based on:
    - Reference number overlap
    - Reply/response patterns
    - Sender/recipient overlap
    - Chronological ordering
    - Topic similarity
    """

    # Minimum Jaccard similarity for topic edges
    TOPIC_SIMILARITY_THRESHOLD = 0.3

    def __init__(self):
        """Initialize light graph."""
        self.graph = DocumentGraph()
        self._load_graph()

    def _load_graph(self):
        """Load graph from disk."""
        if GRAPH_FILE.exists():
            try:
                with open(GRAPH_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.graph = DocumentGraph(
                    nodes=data.get('nodes', {}),
                    edges=data.get('edges', []),
                    metadata=data.get('metadata', {}),
                )
                logger.info(f"[LightGraph] Loaded {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges")
            except Exception as e:
                logger.error(f"[LightGraph] Error loading graph: {e}")
                self.graph = DocumentGraph()

    def _save_graph(self):
        """Persist graph to disk."""
        try:
            data = {
                'nodes': self.graph.nodes,
                'edges': self.graph.edges,
                'metadata': {
                    'updated_at': datetime.now().isoformat(),
                    'node_count': len(self.graph.nodes),
                    'edge_count': len(self.graph.edges),
                },
            }
            with open(GRAPH_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"[LightGraph] Saved graph: {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges")
        except Exception as e:
            logger.error(f"[LightGraph] Error saving graph: {e}")

    def add_notice(self, notice: NoticeMetadata):
        """Add a document node from notice metadata."""
        node = GraphNode(
            doc_id=notice.doc_id,
            date=notice.date,
            sender=notice.sender,
            recipient=notice.recipient,
            subject=notice.subject,
            topics=notice.key_topics,
            ref_numbers=notice.ref_numbers,
            file_name=notice.file_name,
            doc_type=notice.doc_type,
        )
        self.graph.nodes[notice.doc_id] = asdict(node)
        logger.info(f"[LightGraph] Added node: {notice.doc_id}")

    def build_edges(self):
        """Build all edge types between nodes."""
        logger.info("[LightGraph] Building edges...")

        # Clear existing edges
        self.graph.edges = []

        nodes = list(self.graph.nodes.values())
        n = len(nodes)

        for i in range(n):
            for j in range(i + 1, n):
                node_a = nodes[i]
                node_b = nodes[j]

                # Check for various edge types
                edges = []

                # 1. Reference edges
                ref_edge = self._check_reference_edge(node_a, node_b)
                if ref_edge:
                    edges.append(ref_edge)

                # 2. Same party edges
                party_edge = self._check_same_party_edge(node_a, node_b)
                if party_edge:
                    edges.append(party_edge)

                # 3. Topic similarity edges
                topic_edge = self._check_topic_edge(node_a, node_b)
                if topic_edge:
                    edges.append(topic_edge)

                # Add edges to graph
                self.graph.edges.extend([asdict(e) for e in edges])

        # 4. Build chronological chains within parties/threads
        self._build_chronological_edges()

        logger.info(f"[LightGraph] Built {len(self.graph.edges)} edges")
        self._save_graph()

    def _check_reference_edge(
        self,
        node_a: Dict,
        node_b: Dict,
    ) -> Optional[GraphEdge]:
        """Check for reference number overlap."""
        refs_a = set(node_a.get('ref_numbers', []))
        refs_b = set(node_b.get('ref_numbers', []))

        if not refs_a or not refs_b:
            return None

        overlap = refs_a & refs_b
        if overlap:
            weight = min(1.0, len(overlap) / max(len(refs_a), len(refs_b)))
            return GraphEdge(
                from_doc=node_a['doc_id'],
                to_doc=node_b['doc_id'],
                edge_type='references',
                weight=weight,
                why=f"Shared references: {', '.join(list(overlap)[:3])}",
            )
        return None

    def _check_same_party_edge(
        self,
        node_a: Dict,
        node_b: Dict,
    ) -> Optional[GraphEdge]:
        """Check for sender/recipient overlap."""
        parties_a = set()
        parties_b = set()

        if node_a.get('sender'):
            parties_a.add(self._normalize_party(node_a['sender']))
        if node_a.get('recipient'):
            parties_a.add(self._normalize_party(node_a['recipient']))
        if node_b.get('sender'):
            parties_b.add(self._normalize_party(node_b['sender']))
        if node_b.get('recipient'):
            parties_b.add(self._normalize_party(node_b['recipient']))

        if not parties_a or not parties_b:
            return None

        overlap = parties_a & parties_b
        if overlap:
            weight = len(overlap) / max(len(parties_a), len(parties_b))
            return GraphEdge(
                from_doc=node_a['doc_id'],
                to_doc=node_b['doc_id'],
                edge_type='same_party',
                weight=weight,
                why=f"Shared parties: {', '.join(list(overlap)[:2])}",
            )
        return None

    def _check_topic_edge(
        self,
        node_a: Dict,
        node_b: Dict,
    ) -> Optional[GraphEdge]:
        """Check for topic similarity using Jaccard."""
        topics_a = set(t.lower() for t in node_a.get('topics', []))
        topics_b = set(t.lower() for t in node_b.get('topics', []))

        if not topics_a or not topics_b:
            return None

        intersection = topics_a & topics_b
        union = topics_a | topics_b

        if not union:
            return None

        jaccard = len(intersection) / len(union)

        if jaccard >= self.TOPIC_SIMILARITY_THRESHOLD:
            return GraphEdge(
                from_doc=node_a['doc_id'],
                to_doc=node_b['doc_id'],
                edge_type='same_topic',
                weight=jaccard,
                why=f"Shared topics: {', '.join(list(intersection)[:3])}",
            )
        return None

    def _build_chronological_edges(self):
        """Build chronological_next edges within related document groups."""
        # Group nodes by party involvement
        party_groups = defaultdict(list)

        for doc_id, node in self.graph.nodes.items():
            if node.get('sender'):
                party_groups[self._normalize_party(node['sender'])].append(node)
            if node.get('recipient'):
                party_groups[self._normalize_party(node['recipient'])].append(node)

        # Within each party group, sort by date and link
        for party, nodes in party_groups.items():
            dated_nodes = [n for n in nodes if n.get('date')]
            dated_nodes.sort(key=lambda x: x['date'])

            for i in range(len(dated_nodes) - 1):
                node_a = dated_nodes[i]
                node_b = dated_nodes[i + 1]

                # Only create edge if not already connected by other edge types
                existing_edge = any(
                    e['from_doc'] == node_a['doc_id'] and e['to_doc'] == node_b['doc_id']
                    and e['edge_type'] == 'chronological_next'
                    for e in self.graph.edges
                )

                if not existing_edge:
                    self.graph.edges.append(asdict(GraphEdge(
                        from_doc=node_a['doc_id'],
                        to_doc=node_b['doc_id'],
                        edge_type='chronological_next',
                        weight=0.5,
                        why=f"Chronological order for party: {party}",
                    )))

    def _normalize_party(self, name: str) -> str:
        """Normalize party name for comparison."""
        if not name:
            return ""
        # Remove common suffixes and normalize
        name = name.lower().strip()
        for suffix in ['ltd', 'inc', 'corp', 'llc', 'co', 'company', 'limited']:
            name = re.sub(rf'\b{suffix}\b\.?', '', name)
        return re.sub(r'\s+', ' ', name).strip()

    # === Query Methods ===

    def timeline(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        party_filter: Optional[str] = None,
        topic_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get documents in chronological order with optional filters.

        Args:
            start_date: ISO format start date filter
            end_date: ISO format end date filter
            party_filter: Filter by sender/recipient containing this string
            topic_filter: Filter by topic keyword

        Returns:
            List of nodes sorted by date
        """
        results = []

        for doc_id, node in self.graph.nodes.items():
            # Date filter
            node_date = node.get('date')
            if start_date and node_date and node_date < start_date:
                continue
            if end_date and node_date and node_date > end_date:
                continue

            # Party filter
            if party_filter:
                party_lower = party_filter.lower()
                sender = (node.get('sender') or '').lower()
                recipient = (node.get('recipient') or '').lower()
                if party_lower not in sender and party_lower not in recipient:
                    continue

            # Topic filter
            if topic_filter:
                topic_lower = topic_filter.lower()
                topics = [t.lower() for t in node.get('topics', [])]
                if not any(topic_lower in t for t in topics):
                    continue

            results.append(node)

        # Sort by date
        results.sort(key=lambda x: x.get('date') or '9999-99-99')

        logger.info(f"[LightGraph] Timeline query returned {len(results)} documents")
        return results

    def trace_chain(
        self,
        doc_id: str,
        depth: int = 3,
        edge_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Trace the chain of related documents from a starting point.

        Args:
            doc_id: Starting document ID
            depth: Maximum depth to traverse
            edge_types: Filter by edge types (None = all)

        Returns:
            Dict with upstream and downstream chains
        """
        if doc_id not in self.graph.nodes:
            return {'upstream': [], 'downstream': [], 'start': None}

        start_node = self.graph.nodes[doc_id]
        visited = {doc_id}

        def traverse(current_id: str, current_depth: int, direction: str) -> List[Dict]:
            if current_depth <= 0:
                return []

            results = []
            for edge in self.graph.edges:
                # Check direction
                if direction == 'upstream':
                    if edge['to_doc'] == current_id:
                        next_id = edge['from_doc']
                    else:
                        continue
                else:  # downstream
                    if edge['from_doc'] == current_id:
                        next_id = edge['to_doc']
                    else:
                        continue

                # Filter by edge type
                if edge_types and edge['edge_type'] not in edge_types:
                    continue

                if next_id in visited:
                    continue

                visited.add(next_id)
                next_node = self.graph.nodes.get(next_id)
                if next_node:
                    results.append({
                        'node': next_node,
                        'edge': edge,
                        'depth': depth - current_depth + 1,
                    })
                    results.extend(traverse(next_id, current_depth - 1, direction))

            return results

        upstream = traverse(doc_id, depth, 'upstream')
        visited = {doc_id}  # Reset for downstream
        downstream = traverse(doc_id, depth, 'downstream')

        return {
            'start': start_node,
            'upstream': sorted(upstream, key=lambda x: x['node'].get('date') or ''),
            'downstream': sorted(downstream, key=lambda x: x['node'].get('date') or ''),
        }

    def explain_link(
        self,
        doc_a: str,
        doc_b: str,
    ) -> List[Dict[str, Any]]:
        """
        Explain the relationship between two documents.

        Returns:
            List of edges connecting the documents with explanations
        """
        edges = []

        for edge in self.graph.edges:
            if (edge['from_doc'] == doc_a and edge['to_doc'] == doc_b) or \
               (edge['from_doc'] == doc_b and edge['to_doc'] == doc_a):
                edges.append(edge)

        # If no direct edges, find shortest path
        if not edges:
            path = self._find_path(doc_a, doc_b, max_depth=3)
            if path:
                return [{'path': path, 'why': 'Indirect connection through shared documents'}]

        return edges

    def _find_path(
        self,
        start: str,
        end: str,
        max_depth: int = 3,
    ) -> Optional[List[str]]:
        """Find shortest path between two documents."""
        if start == end:
            return [start]

        visited = {start}
        queue = [(start, [start])]

        while queue:
            current, path = queue.pop(0)

            if len(path) > max_depth:
                continue

            # Find neighbors
            neighbors = set()
            for edge in self.graph.edges:
                if edge['from_doc'] == current:
                    neighbors.add(edge['to_doc'])
                elif edge['to_doc'] == current:
                    neighbors.add(edge['from_doc'])

            for neighbor in neighbors:
                if neighbor == end:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return None

    def find_related(
        self,
        doc_id: str,
        edge_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Find all directly related documents."""
        if doc_id not in self.graph.nodes:
            return []

        related = []
        for edge in self.graph.edges:
            if edge['from_doc'] == doc_id:
                related_id = edge['to_doc']
            elif edge['to_doc'] == doc_id:
                related_id = edge['from_doc']
            else:
                continue

            if edge_types and edge['edge_type'] not in edge_types:
                continue

            related_node = self.graph.nodes.get(related_id)
            if related_node:
                related.append({
                    'node': related_node,
                    'edge': edge,
                })

        return sorted(related, key=lambda x: x['edge'].get('weight', 0), reverse=True)

    def search_by_action(self, action: str) -> List[Dict[str, Any]]:
        """Find documents mentioning a specific action."""
        results = []
        action_lower = action.lower()

        for doc_id in self.graph.nodes:
            # Load full notice to check actions
            notice_path = NOTICES_DIR / f"{doc_id}.json"
            if notice_path.exists():
                try:
                    with open(notice_path, 'r', encoding='utf-8') as f:
                        notice = json.load(f)
                    if action_lower in [a.lower() for a in notice.get('actions', [])]:
                        results.append({
                            'node': self.graph.nodes[doc_id],
                            'notice': notice,
                        })
                except Exception:
                    pass

        return results

    def get_statistics(self) -> Dict[str, Any]:
        """Get graph statistics."""
        edge_type_counts = defaultdict(int)
        for edge in self.graph.edges:
            edge_type_counts[edge['edge_type']] += 1

        return {
            'node_count': len(self.graph.nodes),
            'edge_count': len(self.graph.edges),
            'edge_types': dict(edge_type_counts),
            'has_dates': sum(1 for n in self.graph.nodes.values() if n.get('date')),
            'has_parties': sum(1 for n in self.graph.nodes.values() if n.get('sender') or n.get('recipient')),
        }

    def rebuild_from_notices(self):
        """Rebuild entire graph from saved notices."""
        logger.info("[LightGraph] Rebuilding graph from notices...")

        self.graph = DocumentGraph()

        # Load all notices
        for notice_path in NOTICES_DIR.glob("*.json"):
            try:
                with open(notice_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                notice = NoticeMetadata(**data)
                self.add_notice(notice)
            except Exception as e:
                logger.warning(f"[LightGraph] Error loading notice {notice_path.name}: {e}")

        # Build edges
        self.build_edges()
        logger.info(f"[LightGraph] Rebuilt: {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges")


# Singleton
_graph: Optional[LightGraph] = None


def get_light_graph() -> LightGraph:
    """Get or create LightGraph singleton."""
    global _graph
    if _graph is None:
        _graph = LightGraph()
    return _graph


def add_document_to_graph(notice: NoticeMetadata):
    """Add a document to the graph and rebuild edges."""
    graph = get_light_graph()
    graph.add_notice(notice)
    graph.build_edges()
