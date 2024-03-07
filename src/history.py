class TrackingHistory:
    class ChainNode:
        def __init__(self, figure_id, next_node: "ChainNode" = None, prev_node: "ChainNode" = None):
            self.figure_id = figure_id
            self.next_node = next_node
            self.prev_node = prev_node

        def set_next(self, node: "ChainNode"):
            self.next_node = node

        def get_next(self) -> "ChainNode":
            return self.next_node

        def set_prev(self, node: "ChainNode"):
            self.prev_node = node

        def get_prev(self) -> "ChainNode":
            return self.prev_node

    def __init__(self):
        self.all_figures = {}
        self.user_figures = set()

    def is_prediction(self, figure_id):
        return figure_id not in self.user_figures

    def add(self, figure_id, pred_figure_ids):
        current_node = self.all_figures.setdefault(figure_id, self.ChainNode(figure_id))
        self.user_figures.add(figure_id)
        for pred_figure_id in pred_figure_ids:
            pred_node = self.all_figures.setdefault(pred_figure_id, self.ChainNode(pred_figure_id))
            pred_node.set_prev(current_node)
            current_node.set_next(pred_node)
            current_node = pred_node

    def get(self, figure_id, frames: int = 5):
        current_node = self.all_figures.get(figure_id, None)
        if current_node is None:
            return [None] * frames
        figure_ids = []
        for _ in range(frames):
            current_node = current_node.get_next()
            if current_node is None:
                figure_ids.extend([None] * (frames - len(figure_ids)))
                break
            if not self.is_prediction(current_node.figure_id):
                break
            figure_ids.append(current_node.figure_id)
        return figure_ids

    def remove(self, figure_id):
        if figure_id in self.user_figures:
            self.user_figures.remove(figure_id)


tracking_history = TrackingHistory()
