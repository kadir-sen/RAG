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
    cc_list: List[str] = field(default_factory=list)
    direction: Optional[str] = None  # outgoing/incoming/internal
    contract_ref: Optional[str] = None
    project_name: Optional[str] = None
    actions: List[str] = field(default_factory=list)


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
            cc_list=getattr(notice, 'cc_list', []) or [],
            direction=getattr(notice, 'direction', None),
            contract_ref=getattr(notice, 'contract_ref', None),
            project_name=getattr(notice, 'project_name', None),
            actions=getattr(notice, 'actions', []) or [],
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

                # 4. Contract reference edges
                contract_edge = self._check_contract_edge(node_a, node_b)
                if contract_edge:
                    edges.append(contract_edge)

                # 5. Reply-to edges (B's sender = A's recipient, or vice versa)
                reply_edge = self._check_reply_edge(node_a, node_b)
                if reply_edge:
                    edges.append(reply_edge)

                # Add edges to graph
                self.graph.edges.extend([asdict(e) for e in edges])

        # 6. Build chronological chains within parties/threads
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

    def _check_contract_edge(
        self,
        node_a: Dict,
        node_b: Dict,
    ) -> Optional[GraphEdge]:
        """Check for shared contract reference."""
        ref_a = node_a.get('contract_ref')
        ref_b = node_b.get('contract_ref')

        if ref_a and ref_b and ref_a.lower() == ref_b.lower():
            return GraphEdge(
                from_doc=node_a['doc_id'],
                to_doc=node_b['doc_id'],
                edge_type='same_contract',
                weight=0.9,
                why=f"Same contract: {ref_a}",
            )
        return None

    def _check_reply_edge(
        self,
        node_a: Dict,
        node_b: Dict,
    ) -> Optional[GraphEdge]:
        """Check for reply pattern (A's recipient is B's sender and B is later)."""
        sender_a = node_a.get('sender', '')
        recipient_a = node_a.get('recipient', '')
        sender_b = node_b.get('sender', '')
        recipient_b = node_b.get('recipient', '')
        date_a = node_a.get('date', '')
        date_b = node_b.get('date', '')

        if not (sender_a and recipient_a and sender_b and recipient_b):
            return None

        # B replies to A: A's recipient = B's sender AND B's recipient = A's sender
        a_recv_norm = self._normalize_party(recipient_a)
        b_send_norm = self._normalize_party(sender_b)
        a_send_norm = self._normalize_party(sender_a)
        b_recv_norm = self._normalize_party(recipient_b)

        if a_recv_norm == b_send_norm and a_send_norm == b_recv_norm:
            # Determine direction based on date
            if date_a and date_b and date_b >= date_a:
                return GraphEdge(
                    from_doc=node_a['doc_id'],
                    to_doc=node_b['doc_id'],
                    edge_type='reply_to',
                    weight=0.85,
                    why=f"Reply: {sender_b} replied to {sender_a}",
                )
            elif date_a and date_b and date_a > date_b:
                return GraphEdge(
                    from_doc=node_b['doc_id'],
                    to_doc=node_a['doc_id'],
                    edge_type='reply_to',
                    weight=0.85,
                    why=f"Reply: {sender_a} replied to {sender_b}",
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

    def communication_flow(
        self,
        party: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get communication flow: who sent to whom and when.

        Args:
            party: Optional filter by party name

        Returns:
            List of communication records sorted by date
        """
        results = []

        for doc_id, node in self.graph.nodes.items():
            sender = node.get('sender')
            recipient = node.get('recipient')
            date = node.get('date')

            if not sender and not recipient:
                continue

            if party:
                party_lower = party.lower()
                sender_lower = (sender or '').lower()
                recipient_lower = (recipient or '').lower()
                if party_lower not in sender_lower and party_lower not in recipient_lower:
                    continue

            results.append({
                'doc_id': doc_id,
                'date': date or 'Unknown',
                'sender': sender or 'Unknown',
                'recipient': recipient or 'Unknown',
                'subject': node.get('subject', ''),
                'direction': node.get('direction', 'unknown'),
                'doc_type': node.get('doc_type', ''),
                'file_name': node.get('file_name', ''),
                'cc_list': node.get('cc_list', []),
                'actions': node.get('actions', []),
            })

        results.sort(key=lambda x: x.get('date') or '9999-99-99')
        return results

    def project_documents(
        self,
        project_filter: Optional[str] = None,
        contract_ref: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all documents for a project or contract reference.

        Args:
            project_filter: Filter by project name
            contract_ref: Filter by contract reference

        Returns:
            List of documents sorted by date
        """
        results = []

        for doc_id, node in self.graph.nodes.items():
            # Project filter
            if project_filter:
                proj_lower = project_filter.lower()
                node_project = (node.get('project_name') or '').lower()
                node_subject = (node.get('subject') or '').lower()
                if proj_lower not in node_project and proj_lower not in node_subject:
                    continue

            # Contract ref filter
            if contract_ref:
                ref_lower = contract_ref.lower()
                node_ref = (node.get('contract_ref') or '').lower()
                node_refs = [r.lower() for r in node.get('ref_numbers', [])]
                if ref_lower not in node_ref and not any(ref_lower in r for r in node_refs):
                    continue

            results.append(node)

        results.sort(key=lambda x: x.get('date') or '9999-99-99')
        return results

    def correspondence_between(
        self,
        party_a: str,
        party_b: str,
    ) -> List[Dict[str, Any]]:
        """
        Get all correspondence between two parties.

        Args:
            party_a: First party name
            party_b: Second party name

        Returns:
            List of documents exchanged between the parties
        """
        results = []
        a_lower = party_a.lower()
        b_lower = party_b.lower()

        for doc_id, node in self.graph.nodes.items():
            sender = (node.get('sender') or '').lower()
            recipient = (node.get('recipient') or '').lower()

            # A -> B or B -> A
            if (a_lower in sender and b_lower in recipient) or \
               (b_lower in sender and a_lower in recipient):
                results.append({
                    'node': node,
                    'from': node.get('sender', 'Unknown'),
                    'to': node.get('recipient', 'Unknown'),
                    'date': node.get('date', 'Unknown'),
                    'subject': node.get('subject', ''),
                })

        results.sort(key=lambda x: x.get('date') or '9999-99-99')
        return results

    def get_all_parties(self) -> List[Dict[str, int]]:
        """
        Get all unique parties with document counts.

        Returns:
            List of {name, sent_count, received_count}
        """
        party_stats = defaultdict(lambda: {'sent': 0, 'received': 0})

        for node in self.graph.nodes.values():
            sender = node.get('sender')
            recipient = node.get('recipient')
            if sender:
                party_stats[self._normalize_party(sender)]['sent'] += 1
            if recipient:
                party_stats[self._normalize_party(recipient)]['received'] += 1

        results = []
        for name, stats in sorted(party_stats.items()):
            results.append({
                'party': name,
                'sent_count': stats['sent'],
                'received_count': stats['received'],
                'total': stats['sent'] + stats['received'],
            })

        return sorted(results, key=lambda x: x['total'], reverse=True)

    def smart_timeline_answer(
        self,
        query: str,
        max_nodes: int = 20,
    ) -> Dict[str, Any]:
        """
        Use LLM to synthesize a natural language answer from timeline data.
        Uses llm_client for caching, cost tracking, and prompt security.

        Args:
            query: User's natural language question
            max_nodes: Maximum nodes to include as context

        Returns:
            Dict with answer and sources
        """
        from . import llm_client
        from .prompt_security import safe_render_prompt, build_system_prompt

        # Gather relevant nodes
        nodes = self.timeline()
        if not nodes:
            return {
                "answer": "No documents in the timeline graph.",
                "sources": [],
            }

        # Build context from nodes
        node_lines = []
        for i, node in enumerate(nodes[:max_nodes], 1):
            date = node.get('date', 'No date')
            sender = (node.get('sender') or 'Unknown')[:40]
            recipient = (node.get('recipient') or 'Unknown')[:40]
            subject = (node.get('subject') or '')[:100]
            doc_type = node.get('doc_type', '')
            direction = node.get('direction', '')
            actions = ', '.join(node.get('actions', [])[:3])
            refs = ', '.join(node.get('ref_numbers', [])[:3])
            cc = ', '.join(node.get('cc_list', [])[:2])

            line = f"{i}. Date: {date} | Type: {doc_type} | Direction: {direction}"
            line += f"\n   From: {sender} -> To: {recipient}"
            if cc:
                line += f" (CC: {cc})"
            line += f"\n   Subject: {subject}"
            if actions:
                line += f"\n   Actions: {actions}"
            if refs:
                line += f"\n   Refs: {refs}"
            node_lines.append(line)

        # Graph statistics
        stats = self.get_statistics()
        parties = self.get_all_parties()

        context = "\n\n".join(node_lines)
        party_context = ""
        if parties:
            party_lines = [f"- {p['party']}: {p['sent_count']} sent, {p['received_count']} received"
                           for p in parties[:10]]
            party_context = "\nActive parties:\n" + "\n".join(party_lines)

        prompt = safe_render_prompt(
            "Answer the question based ONLY on the document timeline data below.\n\n"
            "DOCUMENT TIMELINE ({node_count} documents, {edge_count} relationships):\n"
            "{timeline_context}\n"
            "{party_context}\n\n"
            "{user_query}\n\n"
            "RULES:\n"
            "1. Only use information present in the timeline data above\n"
            "2. Reference specific dates, senders, recipients, and subjects\n"
            "3. If the answer is not in the data, say so clearly\n"
            "4. Be concise but thorough\n"
            "5. Format dates and names clearly",
            user_query=query,
            node_count=str(stats['node_count']),
            edge_count=str(stats['edge_count']),
            timeline_context=context,
            party_context=party_context,
        )
        system = build_system_prompt(
            "You are an expert assistant for construction project document analysis."
        )

        try:
            resp = llm_client.generate_text(prompt, system=system, max_tokens=1024)
            answer = resp.text

            # Record telemetry
            from .telemetry import get_current_trace
            trace = get_current_trace()
            if trace:
                trace.record_llm_call(resp.usage)

        except Exception as e:
            logger.error(f"[LightGraph] LLM synthesis error: {e}")
            # Fallback to basic listing
            answer = f"Found {len(nodes)} documents:\n\n"
            for i, node in enumerate(nodes[:15], 1):
                date = node.get('date', 'No date')
                sender = (node.get('sender') or 'Unknown')[:30]
                recipient = (node.get('recipient') or 'Unknown')[:30]
                subject = (node.get('subject') or '')[:60]
                answer += f"{i}. {date} | {sender} -> {recipient}: {subject}\n"

        # Build sources
        sources = []
        for node in nodes[:max_nodes]:
            sources.append({
                "type": "graph_node",
                "doc_id": node.get('doc_id'),
                "file_name": node.get('file_name', ''),
                "date": node.get('date', ''),
                "sender": node.get('sender', ''),
                "recipient": node.get('recipient', ''),
            })

        return {
            "answer": answer,
            "sources": sources,
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
