import os
from dotenv import load_dotenv
import pandas as pd
import src.globals as g
import supervisely as sly
import supervisely.app.development as sly_app_development
from supervisely.app.widgets import (
    Container,
    Button,
    Field,
    Table,
    Text,
    SelectAppSession,
    Input,
)

table = Table()
run_button = Button("Predict next frame")
session_select = Input(value="52859")

layout = Container(
    widgets=[
        table,
        session_select,
        run_button
    ]
)
app = sly.Application(layout=layout)

# Initializing global variables.
api = None
project_meta = None
event_video: sly.Event.ManualSelected.VideoChanged = None
event_figure: sly.Event.ManualSelected.FigureChanged = None
annotation: sly.VideoAnnotation = None
key_id_map: sly.KeyIdMap = None
# session_id = None
# dataset_id = None
# video_id = None
# project_id = None
frame_idx = None

selected_objects = []  # [{checked, object_id, name}]

@app.event(sly.Event.ManualSelected.VideoChanged)
def video_changed(event_api: sly.Api, event: sly.Event.ManualSelected.VideoChanged):
    print("video_changed")
    global api, event_video, project_meta, selected_objects, annotation, key_id_map, frame_idx
    
    api = event_api
    event_video = event
    frame_idx = event_video.frame
    project_meta = sly.ProjectMeta.from_json(api.project.get_meta(event_video.project_id))
    
    # download annotation
    annotation, key_id_map = download_annotation(api, event_video.video_id)

    # create selected_objects
    selected_objects = []
    frame_items = get_frame_items(annotation, key_id_map, frame_idx)
    update_selected_objects(frame_items)
    update_table()


@app.event(sly.Event.ManualSelected.FigureChanged)
def figure_changed(event_api: sly.Api, event: sly.Event.ManualSelected.FigureChanged):
    print("figure_changed")
    global event_figure, frame_idx, annotation, key_id_map
    if event.figure_id is None:
        return
    event_figure = event
    frame_idx = event_figure.frame

    annotation, key_id_map = download_annotation(api, event_video.video_id)
    frame_items = get_frame_items(annotation, key_id_map, frame_idx)
    update_selected_objects(frame_items)
    update_table()


@run_button.click
def predict_next_frame():
    frame_items = get_frame_items(annotation, key_id_map, frame_idx)
    figure_ids, object_ids, figures = get_figures_and_objects(frame_items, selected_objects)
    video_id = event_video.video_id
    # direction = 'forward'
    frames_count = 2
    task_id = int(session_select.get_value()) #or 52859
    bboxes = [figure.geometry.to_json() for figure in figures]
    data = {
        "frameIndex": frame_idx,
        "frames": frames_count,
        "videoId": video_id,
        "bboxes": bboxes,
    }

    sly.json.dump_json_file(data, "data.json")

    g.api.retry_count = 1
    response = g.api.task.send_request(task_id, "predict", {}, context=data)
    sly.json.dump_json_file(response, "response.json")

    start_frame_idx = frame_idx
    for i, bboxes in enumerate(response):
        for object_id, bbox in zip(object_ids, bboxes):
            frame = start_frame_idx + i + 1
            g.api.video.figure.create(
                video_id, object_id, frame, bbox, sly.Rectangle.geometry_name(), "auto"
            )


def update_table():
    table.read_pandas(pd.DataFrame(selected_objects))


@table.click
def handle_table_click(datapoint: Table.ClickedDataPoint):
    # switch checked state of the clicked row
    for item in selected_objects:
        if item['object_id'] == datapoint.row['object_id']:
            if item['checked'] == "✅":
                item['checked'] = "❌"
            else:
                item['checked'] = "✅"
    update_table()


def get_frame_items(ann: sly.VideoAnnotation, key_id_map: sly.KeyIdMap, frame_idx: int, geometry_type=sly.Rectangle):
    # Find the annotation for the frame_idx
    frame_annotation = None
    for frame in ann.frames:
        frame: sly.Frame
        if frame.index == frame_idx:
            frame_annotation = frame
            break
    assert frame_annotation is not None, "Frame not found in the annotation"

    # Extract figures from the frame annotation
    frame_items = []
    for figure in frame_annotation.figures:
        if isinstance(figure.geometry, geometry_type) is False:
            continue
        item = {
            'figure_id': key_id_map.get_figure_id(figure.key()),
            'object_id': key_id_map.get_object_id(figure.parent_object.key()),
            'name': figure.parent_object.obj_class.name,
            'figure': figure,
        }
        frame_items.append(item)

    return frame_items


def get_figures_and_objects(frame_items, selected_objects):
    figures_id = []
    objects_id = []
    figures = []
    for item in frame_items:
        item_s = [item_s for item_s in selected_objects if item_s['object_id'] == item['object_id']]
        if item_s and item_s[0]['checked'] == "✅":
            figures_id.append(item['figure_id'])
            objects_id.append(item['object_id'])
            figures.append(item['figure'])
    return figures_id, objects_id, figures


def update_selected_objects(frame_items):
    # detecting new objects
    global selected_objects
    for item in frame_items:
        if item['object_id'] not in [item['object_id'] for item in selected_objects]:
            item['checked'] = "❌"
            item.pop('figure_id')
            item.pop('figure')
            selected_objects.append(item)


def download_annotation(api: sly.Api, video_id):
    ann_json = api.video.annotation.download(video_id)
    key_id_map = sly.KeyIdMap()
    ann = sly.VideoAnnotation.from_json(ann_json, project_meta, key_id_map)
    return ann, key_id_map
