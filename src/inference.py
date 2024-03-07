import asyncio
import json
from typing import List, Union

import requests
import supervisely as sly
from supervisely.api.entity_annotation.figure_api import FigureInfo

import src.globals as g
import src.utils as utils


def get_nn_url(geometry_type) -> str:
    return g.NN_URLS.get(geometry_type, None)


def get_smarttool_input(figure_meta: dict) -> utils.SmartToolInput:
    try:
        smi = figure_meta["smartToolInput"]
        return utils.SmartToolInput.from_json(smi)
    except KeyError:
        return None


def _fix_unbound(rect: utils.Prediction, point: utils.Prediction):
    rect_geom = sly.Rectangle.from_json(rect.geometry_data)
    point_geom = sly.Point.from_json(point.geometry_data)
    if rect_geom.contains_point_location(point_geom):
        return point
    if point_geom.col < rect_geom.left:
        point_geom = sly.Point(point_geom.row, rect_geom.left)
    if point_geom.col > rect_geom.right:
        point_geom = sly.Point(point_geom.row, rect_geom.right)
    if point_geom.row < rect_geom.top:
        point_geom = sly.Point(rect_geom.top, point_geom.col)
    if point_geom.row > rect_geom.bottom:
        point_geom = sly.Point(rect_geom.bottom, point_geom.col)
    return utils.Prediction(
        frame_index=point.frame_index,
        geometry_data=point_geom.to_json(),
        geometry_type=point.geometry_type,
        meta=point.meta,
    )


async def _predict_smarttool(
    video_id: int,
    frame_index: int,
    frames_count: int,
    crop_predictions: List[List[utils.Prediction]],
    pos_predictions: List[List[utils.Prediction]],
    neg_predictions: List[List[utils.Prediction]],
) -> List[List[dict]]:
    sly.logger.debug(
        "Crop and points predictions",
        extra={
            "crop": [[j.to_json() for j in i] for i in crop_predictions],
            "positive": [[j.to_json() for j in i] for i in pos_predictions],
            "negative": [[j.to_json() for j in i] for i in neg_predictions],
        },
    )

    def _to_rect(predictions: List[utils.Prediction]):
        data = predictions[0].geometry_data
        r = sly.Rectangle.from_json(data)
        return {"x": r.left, "y": r.top}, {"x": r.right, "y": r.bottom}

    def _to_points(predictions: List[utils.Prediction]):
        return [
            {
                "x": prediction.geometry_data["points"]["exterior"][0][0],
                "y": prediction.geometry_data["points"]["exterior"][0][1],
            }
            for prediction in predictions
        ]

    crops = [_to_rect(frame_predictions) for frame_predictions in crop_predictions]
    positives = [_to_points(frame_predictions) for frame_predictions in pos_predictions]
    negatives = [_to_points(frame_predictions) for frame_predictions in neg_predictions]
    sly.logger.debug("Crops", extra={"crops": crops})
    sly.logger.debug("Positives", extra={"positives": positives})
    sly.logger.debug("Negatives", extra={"negatives": negatives})
    nn_url = get_nn_url("smarttool")
    settings = {
        "state": [
            {
                "crop": crop,
                "positive": positive,
                "negative": negative,
                "video": {"video_id": video_id, "frame_index": frame_index + i + 1},
                "request_uid": f"{video_id}_{frame_index + i + 1}",
            }
            for i, (crop, positive, negative) in enumerate(zip(crops, positives, negatives))
        ]
    }
    frames = g.api.video.frame.download_bytes(
        video_id, frame_indexes=list(range(frame_index + 1, frame_index + frames_count + 1))
    )
    files = (
        ("files", (f"frame_{i}", f_bytes, "application/octet-stream"))
        for i, f_bytes in enumerate(frames)
    )
    files = (
        *files,
        ("settings", (None, json.dumps(settings), "application/json")),
    )
    r = requests.post(f"{nn_url}/smart_segmentation_files", files=files, timeout=120)
    try:
        sly.logger.debug("ClickSeg response", extra=r.json())
    except requests.JSONDecodeError:
        sly.logger.debug("ClickSeg response", extra={"text": r.text})

    result = []
    r_data = r.json()
    for frame in r_data["result"]:
        origin = frame.get("origin")
        bitmap = frame.get("bitmap")
        geometry = sly.Bitmap.from_json(
            {
                "bitmap": {"origin": [origin["x"], origin["y"]], "data": bitmap},
                "shape": "bitmap",
                "geometryType": "bitmap",
            }
        )
        result.append([{"type": geometry.geometry_name(), "data": geometry.to_json()}])
    return result


async def _run_smarttool(
    smarttool_input: utils.SmartToolInput,
    video_id: int,
    frame_idx: int,
    frames_count: int,
    figure_id: int,
) -> List[List[utils.Prediction]]:
    smarttool_input_data = smarttool_input.to_json()
    crop = smarttool_input_data["crop"]
    positive = smarttool_input_data["positive"]
    negative = smarttool_input_data["negative"]
    [top, bottom] = sorted([crop[0][1], crop[1][1]])
    [left, right] = sorted([crop[0][0], crop[1][0]])
    crop_rect = sly.Rectangle(top, left, bottom, right)

    crop_predictions_task = asyncio.create_task(
        _predict_geometry(
            [crop_rect.to_json()],
            crop_rect.geometry_name(),
            video_id,
            frame_idx,
            frames_count,
        )
    )
    pos_predictions_task = asyncio.create_task(
        _predict_geometry(
            [sly.Point(point[1], point[0]).to_json() for point in positive],
            sly.Point.geometry_name(),
            video_id,
            frame_idx,
            frames_count,
        )
    )
    # asyncio.create_task(
    #     _predict_geometry(
    #         [sly.Point(point[1], point[0]).to_json() for point in negative],
    #         sly.Point.geometry_name(),
    #         video_id,
    #         frame_idx,
    #         frames_count,
    #     )
    # )
    crop_predictions, pos_predictions = await asyncio.gather(
        crop_predictions_task, pos_predictions_task
    )
    neg_predictions = []
    rect = crop_rect
    points = [sly.Point(point[1], point[0]) for point in negative]
    for i in range(frames_count):
        points = utils.move_points_relative(
            rect, points, sly.Rectangle.from_json(crop_predictions[i][0].geometry_data)
        )
        neg_predictions.append(
            [
                utils.Prediction(
                    frame_index=frame_idx + i + 1,
                    geometry_data=point.to_json(),
                    geometry_type=sly.Point.geometry_name(),
                )
                for point in points
            ]
        )
        rect = sly.Rectangle.from_json(crop_predictions[i][0].geometry_data)
    pos_predictions = [
        [_fix_unbound(crop_predictions[i][0], pp) for pp in pos_predictions[i]]
        for i in range(frames_count)
    ]
    neg_predictions = [
        [_fix_unbound(crop_predictions[i][0], pp) for pp in neg_predictions[i]]
        for i in range(frames_count)
    ]
    smarttool_predictions = await _predict_smarttool(
        video_id, frame_idx, frames_count, crop_predictions, pos_predictions, neg_predictions
    )
    predictions = []
    for i, frame_predictions in enumerate(
        zip(crop_predictions, pos_predictions, neg_predictions, smarttool_predictions)
    ):
        crops, pos_points, neg_points, smarttools = frame_predictions
        prediction = utils.Prediction(
            frame_index=frame_idx + i + 1,
            geometry_data=smarttools[0]["data"],
            geometry_type=smarttools[0]["type"],
            meta=utils.Meta(
                smi=utils.SmartToolInput(
                    crop=sly.Rectangle.from_json(crops[0].geometry_data),
                    positive=[sly.Point.from_json(p.geometry_data) for p in pos_points],
                    negative=[sly.Point.from_json(n.geometry_data) for n in neg_points],
                    visible=True,
                ),
                track_id=utils.get_figure_track_id(figure_id),
                tool="smart",
            ),
        )
        predictions.append([prediction])
    return predictions


async def _predict_geometry(
    geometries_data: List[dict],
    geometry_type: str,
    video_id: int,
    frame_idx: int,
    frames_count: int,
) -> List[List[utils.Prediction]]:
    geometries = [{"type": geometry_type, "data": geom_data} for geom_data in geometries_data]
    data = {
        "video_id": video_id,
        "frame_index": frame_idx,
        "frames": frames_count,
        "input_geometries": geometries,
    }
    inf_url = get_nn_url(geometry_type)
    if inf_url is None:
        sly.logger.error("Failed to run inference: no NN URL for geometry type %s", geometry_type)
        return []
    sly.logger.debug(
        "Running inference",
        extra={
            "frame_idx": frame_idx,
            "frames_count": frames_count,
            "geometry_type": geometry_type,
        },
    )
    results = None
    try:
        response = requests.post(f"{inf_url}/inference", json={"context": data}, timeout=120)
        response.raise_for_status()
        response = response.json()
        results = response["result"]
    except Exception:
        sly.logger.error("Failed to run inference on cached files", exc_info=True)
        g.api.retry_count = 1
        files = g.api.video.frame.download_bytes(
            video_id, frame_indexes=list(range(frame_idx, frame_idx + frames_count + 1))
        )
        files = [
            ("files", (f"frame_{fr_idx}", f_bytes, "application/octet-stream"))
            for fr_idx, f_bytes in zip(range(frame_idx, frame_idx + frames_count + 1), files)
        ]
        files = [
            *files,
            ("settings", (None, json.dumps(data), "application/json")),
        ]
        response = requests.post(
            f"{inf_url}/inference_files",
            files=files,
            timeout=120,
        ).json()
        results = response["result"]
    if geometry_type == sly.Bitmap.geometry_name():
        frame_size = (
            g.STATE.current_video_info.frame_height,
            g.STATE.current_video_info.frame_width,
        )
        results = [
            [
                {
                    "type": geometry_type,
                    "data": utils.smoothen_mask(
                        sly.Bitmap.from_json(prediction["data"]), frame_size
                    ).to_json(),
                }
                for prediction in frame_predictions
            ]
            for frame_predictions in results
        ]
    results = [
        [
            utils.Prediction(
                frame_index=frame_idx + i + 1,
                geometry_data=prediction["data"],
                geometry_type=prediction["type"],
            )
            for prediction in frame_predictions
        ]
        for i, frame_predictions in enumerate(results)
    ]
    return results


@sly.timeit
def run(
    video_id: int,
    frame_idx: int,
    figure: Union[FigureInfo, sly.VideoFigure],
    frames_count: int = 5,
) -> List[List[utils.Prediction]]:
    if isinstance(figure, sly.VideoFigure):
        geom_type = figure.geometry.geometry_name()
        geom_data = figure.geometry.to_json()
        figure_meta = figure.get_meta()
    else:
        geom_type = figure.geometry_type
        geom_data = figure.geometry
        figure_meta = figure.meta

    smarttool_input = get_smarttool_input(figure_meta)
    if smarttool_input is not None and smarttool_input.visible:
        return asyncio.run(
            _run_smarttool(smarttool_input, video_id, frame_idx, frames_count, figure.id)
        )
    return asyncio.run(_predict_geometry([geom_data], geom_type, video_id, frame_idx, frames_count))
