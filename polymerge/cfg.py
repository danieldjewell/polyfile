import graphviz
import networkx as nx

from . import polymerge, polytracker


class DiGraph(nx.DiGraph):
    def __init__(self):
        super().__init__()
        self._dominator_forest: DiGraph = None

    @property
    def dominator_forest(self):
        if self._dominator_forest is not None:
            return self._dominator_forest
        self._dominator_forest = DiGraph()
        for root in [n for n, d in self.in_degree() if d == 0]:
            for node, dominated_by in nx.immediate_dominators(self, root).items():
                if node != dominated_by:
                    self._dominator_forest.add_edge(dominated_by, node)
        return self._dominator_forest

    def to_dot(self, comment: str = None, labeler=str) -> graphviz.Digraph:
        if comment is not None:
            dot = graphviz.Digraph(comment=comment)
        else:
            dot = graphviz.Digraph()
        node_ids = {node: i for i, node in enumerate(self.nodes)}
        for node in self.nodes:
            dot.node(f'func{node_ids[node]}', label=labeler(node))
        for caller, callee in self.edges:
            dot.edge(f'func{node_ids[caller]}', f'func{node_ids[callee]}')
        return dot


class CFG(DiGraph):
    def __init__(self, trace):
        super().__init__()
        self.trace: polytracker.ProgramTrace = trace

    def to_dot(self, merged_json_obj=None, only_labeled_functions=False) -> graphviz.Digraph:
        if merged_json_obj is not None:
            function_labels = {
                func_name: ', '.join(['::'.join(label) for label in labels])
                for func_name, labels in polymerge.function_labels(merged_json_obj).items()
            }
        else:
            function_labels = {}

        def labeler(f):
            if f.name in function_labels:
                return f"{f.name} ({function_labels[f.name]})"
            else:
                return f.name

        return super().to_dot(comment='PolyTracker Program Trace', labeler=labeler)
