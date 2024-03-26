import datetime
import json
from typing import List
import uuid
import pytz
import requests

import supervisely as sly
from supervisely.app.widgets import Container, Button, InputNumber, Field, Checkbox, NotificationBox
from supervisely.api.entity_annotation.figure_api import FigureInfo

import src.globals as g
import src.inference as inference
import src.tracking as tracking
from src.history import tracking_history

frame_count_input = InputNumber(10, min=1, step=1)
all_frames_checkbox = Checkbox("All frames")
frame_count_field = Field(
    content=Container(widgets=[frame_count_input, all_frames_checkbox]),
    title="Frame count",
    description="Set frame count for caching and inference",
)


@all_frames_checkbox.value_changed
def all_frames_changed(is_checked):
    if is_checked:
        frame_count_input.disable()
    else:
        frame_count_input.enable()


start_frame_input = InputNumber(0, min=0, step=1)
start_frame_field = Field(title="Start frame", content=start_frame_input)

task_id_input = InputNumber(0, min=0, step=1)
task_id_input_field = Field(title="Task ID", content=task_id_input)
run_on_all_objects_button = Button("Track all objects")

event_mock_cache_video_button = Button("Cache video")

# event_mock_frame_changed_button = Button("Frame changed")
# event_mock_frame_changed_input = InputNumber(0, min=0, step=1)
# event_mock_frame_changed_field = Field(
#     content=Container(widgets=[event_mock_frame_changed_input, event_mock_frame_changed_button]),
#     title="Mock frame changed event",
#     description="Click to mock frame changed event",
# )

# event_mock_figure_deleted_button = Button("Delete Figure")
# event_mock_figure_deleted_field = Field(
#     content=event_mock_figure_deleted_button,
#     title="Mock figure deleted event",
#     description="Select figure and click to delete figure and mock figure deleted event",
# )

running_inference_notification_title = "Running inference"
running_inference_notification = NotificationBox("Running inference", "info")
running_inference_notification.hide()
widgets_container = Container(
    widgets=[
        start_frame_field,
        frame_count_field,
        task_id_input_field,
        run_on_all_objects_button,
        event_mock_cache_video_button,
        # event_mock_frame_changed_field,
        # event_mock_figure_deleted_field,
    ]
)

layout = Container(widgets=[running_inference_notification, widgets_container])
app = sly.Application(layout=layout)


def get_nn_urls():
    nn_urls = set()
    for oc in g.STATE.project_meta.obj_classes:
        if issubclass(oc.geometry_type, sly.AnyGeometry):
            for geom in (
                sly.Rectangle,
                sly.Bitmap,
                sly.Polygon,
                sly.Point,
                sly.Polyline,
                sly.GraphNodes,
            ):
                nn_url = g.NN_URLS.get(geom.geometry_name(), None)
                if nn_url is not None:
                    nn_urls.add(nn_url)
            break
        nn_url = g.NN_URLS.get(oc.geometry_type.geometry_name(), None)
        if nn_url is not None:
            nn_urls.add(nn_url)
    return nn_urls


def get_frame_count(frame_index: int):
    max_frame = g.STATE.current_video_info.frames_count - 1
    if all_frames_checkbox.is_checked():
        return max_frame - frame_index
    frame_count = frame_count_input.get_value()
    if frame_index + frame_count > max_frame:
        frame_count = max_frame - frame_index
    return frame_count


@sly.timeit
def cache_frames(nn_url: str, video_id: int, frame_indexes: List[int]):
    sly.logger.debug(
        "Caching frames",
        extra={"nn_url": nn_url, "video_id": video_id, "frame_indexes": frame_indexes},
    )
    files = g.api.video.frame.download_bytes(video_id, frame_indexes)
    data = {
        "video_id": video_id,
        "frame_indexes": frame_indexes,
    }
    files = [
        ("files", (f"frame_{fr_idx}", f_bytes, "application/octet-stream"))
        for fr_idx, f_bytes in zip(frame_indexes, files)
    ]
    files = [
        *files,
        ("settings", (None, json.dumps(data), "application/json")),
    ]
    r = requests.post(f"{nn_url}/smart_cache_files", files=files)
    r.raise_for_status()


@sly.timeit
def cache_video(video_id: int):
    sly.logger.debug("Caching video", extra={"video_id": video_id})
    # video_info = g.api.video.get_info_by_id(video_id)
    # video_path = Path("/sly_task_data") / video_info.name
    # if not video_path.exists():
    #     g.api.video.download_path(video_id, video_path)
    # data = {
    #     "video_id": video_id,
    # }
    # with open(video_path, "rb") as file:
    #     files = [("files", (video_info.name, file, "application/octet-stream"))]
    #     files = [
    #         *files,
    #         ("settings", (None, json.dumps(data), "application/json")),
    #     ]
    #     r = requests.post(f"{nn_url}/smart_cache_files", files=files)
    #     r.raise_for_status()
    geometries = [oc.geometry_type.geometry_name() for oc in g.STATE.project_meta.obj_classes]
    task_id = task_id_input.get_value()
    try:
        r = g.api.app.send_request(
            task_id,
            "cache_video",
            data={
                "video_id": video_id,
                "server_address": sly.env.server_address(),
                "api_token": sly.env.api_token(),
                "geometries": geometries,
            },
        )
        sly.logger.debug("Cache video response", extra={"response": r})
    except Exception:
        sly.logger.error("Failed to cache video", extra={"video_id": video_id}, exc_info=True)


@event_mock_cache_video_button.click
def cache_video_button():
    cache_video(g.STATE.current_video_id)


def set_video(api: sly.Api, project_id: int, dataset_id: int, video_id: int):
    g.STATE.project_id = project_id
    g.STATE.project_meta = sly.ProjectMeta.from_json(api.project.get_meta(project_id))
    g.STATE.dataset_id = dataset_id
    g.STATE.current_video_id = video_id
    g.STATE.current_video_info = api.video.get_info_by_id(video_id)


@app.event(sly.Event.ManualSelected.VideoChanged)
def video_changed(event_api: sly.Api, event: sly.Event.ManualSelected.VideoChanged):
    print("video_changed")
    set_video(event_api, event.project_id, event.dataset_id, event.video_id)
    cache_video(video_id=event.video_id)


def set_frame(frame_index: int):
    g.STATE.current_frame_index = frame_index


# @event_mock_frame_changed_button.click
# def frame_changed():
#     print("frame_changed")
#     current_frame = event_mock_frame_changed_input.get_value()
#     set_frame(current_frame)
#     frame_count = get_frame_count(current_frame)
#     nn_urls = get_nn_urls()
#     for nn_url in nn_urls:
#         cache_frames(
#             nn_url=nn_url,
#             video_id=g.STATE.current_video_id,
#             frame_indexes=list(range(current_frame, current_frame + frame_count + 1)),
#         )


@run_on_all_objects_button.click
def run_on_all_objects():
    print("run_on_all_objects")
    frame_idx = start_frame_input.get_value()
    frames_count = get_frame_count(frame_idx)
    key_id_map = sly.KeyIdMap()
    annotation = sly.VideoAnnotation.from_json(
        g.api.video.annotation.download(g.STATE.current_video_id), g.STATE.project_meta, key_id_map
    )

    # remove track figures
    figures_to_remove = []
    for figure in annotation.figures:
        if figure.frame_index in range(frame_idx + 1, frame_idx + frames_count + 1):
            figures_to_remove.append(key_id_map.get_figure_id(figure.key()))
    if len(figures_to_remove) > 0:
        figures_to_remove = g.api.video.figure.get_by_ids(g.STATE.dataset_id, figures_to_remove)
        figures_to_remove = [
            fig.id for fig in figures_to_remove if fig.meta.get("trackId", None) is not None
        ]
    if len(figures_to_remove) > 0:
        g.api.video.figure.remove_batch(figures_to_remove)

    # get figures to track
    frame = annotation.frames.get(frame_idx)
    non_track_figure_ids = [
        key_id_map.get_figure_id(fig.key())
        for fig in frame.figures
        if fig.get_meta().get("trackId", None) is None
    ]
    non_track_object_ids = [
        key_id_map.get_object_id(fig.parent_object.key())
        for fig in frame.figures
        if fig.get_meta().get("trackId", None) is None
    ]

    task_id = task_id_input.get_value()
    context = {
        "frameIndex": frame_idx,
        "frames": frames_count,
        "videoId": g.STATE.current_video_id,
        "figureIds": non_track_figure_ids,
        "objectIds": non_track_object_ids,
        "trackId": str(uuid.uuid4()),
        "direction": "forward",
    }
    r = g.api.task.send_request(task_id, "track", data={}, context=context)
    print(
        "Track request: ",
        json.dumps(
            {
                "task_id": task_id,
                "context": context,
                "response": r,
            }
        ),
    )

    # for figure in frame.figures:
    #     figure_id = key_id_map.get_figure_id(figure.key())
    #     object_id = key_id_map.get_object_id(figure.parent_object.key())
    #     predictions = inference.run(
    #         g.STATE.current_video_id,
    #         frame_idx,
    #         figure,
    #         frames_count,
    #     )
    #     frame_indexes = list(range(frame_idx + 1, frame_idx + frames_count + 1))
    #     tracking.upload_predictions(
    #         g.STATE.current_video_id, predictions, frame_indexes, figure_id, object_id
    #     )


# @event_mock_figure_deleted_button.click
# def delete_selected_figure():
#     figure_id = g.STATE.current_figure_id
#     if figure_id is None:
#         return
#     g.STATE.current_figure_id = None
#     g.api.video.figure.remove(figure_id)
#     tracking_history.remove(figure_id)


def is_figure_changed(figure: FigureInfo, updated_at: str):
    print("is_figure_changed")
    if figure.updated_at != updated_at:
        return True
    if figure.updated_at == figure.created_at:
        utc_time_now = datetime.datetime.now(datetime.timezone.utc)
        created_at_utc = datetime.datetime.strptime(
            figure.created_at, "%Y-%m-%dT%H:%M:%S.%fZ"
        ).replace(tzinfo=pytz.UTC)
        return (utc_time_now - created_at_utc).total_seconds() < 3
    return False


@app.event(sly.Event.ManualSelected.FigureChanged)
def _figure_changed(event_api: sly.Api, event: sly.Event.ManualSelected.FigureChanged):
    return
    sly.logger.debug(
        "figure_changed", extra={"event": {str(k): str(v) for k, v in vars(event).items()}}
    )

    video_id = event.video_id
    object_id = event.object_id
    figure_id = event.figure_id
    frame_idx = event.frame

    if figure_id is not None:
        sly.logger.debug("Figure selected", extra={"figure_id": figure_id})
        g.STATE.figure_changed[figure_id] = g.api.video.figure.get_info_by_id(figure_id).updated_at
    else:
        sly.logger.debug("Figure deselected", extra={"figure_id": figure_id})

    # === for mock delete event ===
    g.STATE.current_figure_id = figure_id
    # =============================
    # === for track all objects ===
    g.STATE.dataset_id = event.dataset_id
    # =============================

    previous_figure_data = event.previous_figure
    if previous_figure_data is None:
        sly.logger.debug("Previous figure is None")
        return

    previous_figure = FigureInfo(
        id=previous_figure_data["id"],
        class_id=None,
        updated_at=previous_figure_data["updatedAt"],
        created_at=previous_figure_data["createdAt"],
        entity_id=previous_figure_data["entityId"],
        object_id=previous_figure_data["objectId"],
        project_id=g.STATE.project_id,
        dataset_id=None,
        frame_index=frame_idx,
        geometry_type=previous_figure_data["geometryType"],
        geometry=previous_figure_data["geometry"],
        tags=[],
        meta=previous_figure_data["meta"],
    )

    sti = previous_figure.meta.get("smartToolInput", {})
    sly.logger.debug("SmartToolInput", extra=sti)

    if video_id != g.STATE.current_video_id:
        sly.logger.debug("Set video", extra={"video_id": video_id})
        set_video(event_api, event.project_id, video_id)

    frames_count = get_frame_count(frame_idx)

    # === for UI ===
    event_mock_frame_changed_input.value = frame_idx
    # ==============

    if is_figure_changed(previous_figure, g.STATE.figure_changed.get(previous_figure.id, None)):
        predictions = inference.run(video_id, frame_idx, previous_figure, frames_count)
        frame_indexes = list(range(frame_idx + 1, frame_idx + frames_count + 1))
        tracking.upload_predictions(
            video_id,
            predictions,
            frame_indexes,
            previous_figure.id,
            object_id,
        )
        g.STATE.figure_changed[previous_figure.id] = previous_figure.updated_at


auto_track_sessions = g.api.app.get_sessions(
    g.team_id, g.AUTO_TRACK_MODULE_ID, statuses=[g.api.app.Status.STARTED]
)
if len(auto_track_sessions) > 0:
    task_id_input.value = auto_track_sessions[0].task_id
