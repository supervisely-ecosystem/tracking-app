from typing import List

import supervisely as sly

import src.globals as g
import src.utils as utils
from src.history import tracking_history


@sly.timeit
def upload_predictions(
    video_id: int,
    predictions: List[List[utils.Prediction]],
    frame_indexes: List[int],
    figure_id: int,
    object_id: int,
):
    existing_pred_figure_ids = tracking_history.get(figure_id, len(frame_indexes))
    created_figure_ids = []
    for i, frame_predictions in enumerate(predictions):
        frame_index = frame_indexes[i]
        if i >= len(existing_pred_figure_ids):
            break
        existing_pred_figure_id = existing_pred_figure_ids[i]
        if existing_pred_figure_id is not None:
            try:
                # TODO: check that figure is auto
                g.api.video.figure.remove(existing_pred_figure_id)
            except Exception:
                sly.logger.error(
                    "Failed to remove figure %s", existing_pred_figure_id, exc_info=True
                )

        for prediction in frame_predictions:  # Should be a single geometry
            created_figure_id = g.api.video.figure.create(
                video_id,
                object_id,
                frame_index,
                prediction.geometry_data,
                prediction.geometry_type,
                utils.get_figure_track_id(figure_id),
                meta=prediction.meta.to_json() if prediction.meta is not None else None,
            )
            created_figure_ids.append(created_figure_id)

    tracking_history.add(figure_id, created_figure_ids)
